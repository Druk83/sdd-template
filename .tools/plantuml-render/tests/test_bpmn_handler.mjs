import assert from 'node:assert/strict'
import { createServer, request as httpRequest } from 'node:http'
import test from 'node:test'
import { createBpmnHandler } from '../bpmn-png-handler.mjs'

async function withServer(handler, callback) {
  const server = createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  try {
    await callback(`http://127.0.0.1:${address.port}`)
  } finally {
    await new Promise((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve())
    })
  }
}

function fakeBrowser({
  size = { width: 10, height: 10 },
  setContent = async () => {},
  closePage = async () => {},
  closeBrowser = async () => {}
} = {}) {
  const state = { pages: 0, closed: 0, browserClosed: 0, html: '', requestInterception: false, interceptRequest: null }
  return {
    state,
    browser: {
      async newPage() {
        state.pages += 1
        return {
          async setRequestInterception(value) { state.requestInterception = value },
          on(event, listener) {
            if (event === 'request') state.interceptRequest = listener
          },
          async setContent(html) {
            state.html = html
            await setContent(html)
          },
          async $eval() { return size },
          async setViewport() {},
          async screenshot() { return Buffer.from('png') },
          async close() {
            state.closed += 1
            await closePage()
          }
        }
      },
      async close() {
        state.browserClosed += 1
        await closeBrowser()
      },
      process() {
        return { killed: false, kill() { state.browserKilled = true } }
      }
    }
  }
}

async function post(url, body = '<svg/>') {
  return fetch(`${url}/rasterize`, {
    method: 'POST',
    headers: { 'Content-Type': 'image/svg+xml' },
    body
  })
}

function postChunked(url, chunks) {
  return new Promise((resolve, reject) => {
    const request = httpRequest(`${url}/rasterize`, {
      method: 'POST',
      headers: { 'Transfer-Encoding': 'chunked' }
    }, response => {
      response.resume()
      response.on('end', () => resolve(response.statusCode))
    })
    request.on('error', reject)
    for (const chunk of chunks) request.write(chunk)
    request.end()
  })
}

test('rejects an oversized request body before opening a browser page', async () => {
  const { browser, state } = fakeBrowser()
  await withServer(createBpmnHandler({ browser, maxBodyBytes: 4 }), async url => {
    const response = await post(url, '<svg/>')
    assert.equal(response.status, 413)
    assert.equal(state.pages, 0)
  })
})

test('counts streamed body bytes when content length is not declared', async () => {
  const { browser, state } = fakeBrowser()
  await withServer(createBpmnHandler({ browser, maxBodyBytes: 4 }), async url => {
    const status = await postChunked(url, ['<svg', '/>'])
    assert.equal(status, 413)
    assert.equal(state.pages, 0)
  })
})

test('closes oversized in-flight request instead of draining its body', async () => {
  const { browser, state } = fakeBrowser()
  await withServer(createBpmnHandler({ browser, maxBodyBytes: 4 }), async url => {
    const status = await new Promise((resolve, reject) => {
      const request = httpRequest(url + '/rasterize', {
        method: 'POST',
        headers: { 'Content-Length': '1000' }
      }, response => {
        response.resume()
        response.on('end', () => resolve(response.statusCode))
      })
      request.on('error', reject)
      request.write('12345')
    })
    assert.equal(status, 413)
    assert.equal(state.pages, 0)
  })
})

test('rejects dimensions and pixel area above the configured limits', async () => {
  const { browser, state } = fakeBrowser({ size: { width: 6, height: 5 } })
  await withServer(createBpmnHandler({ browser, maxDimension: 10, maxPixels: 25 }), async url => {
    const response = await post(url)
    assert.equal(response.status, 400)
    assert.equal(state.closed, 1)
  })
})

test('blocks scripts and all network requests from submitted SVG', async () => {
  const { browser, state } = fakeBrowser()
  await withServer(createBpmnHandler({ browser }), async url => {
    const response = await post(url, '<svg onload="fetch(\'http://127.0.0.1/secret\')"><script>1</script></svg>')
    assert.equal(response.status, 200)
    assert.equal(state.requestInterception, true)
    assert.match(state.html, /script-src &#39;none&#39;|script-src 'none'/)
    assert.match(state.html, /connect-src &#39;none&#39;|connect-src 'none'/)
    let aborted = false
    state.interceptRequest({ abort() { aborted = true } })
    assert.equal(aborted, true)
  })
})

test('closes the browser page and returns 504 when rendering exceeds its deadline', async () => {
  const { browser, state } = fakeBrowser({
    setContent: () => new Promise(() => {})
  })
  await withServer(createBpmnHandler({ browser, deadlineMs: 20 }), async url => {
    const response = await post(url)
    assert.equal(response.status, 504)
    assert.equal(state.closed, 1)
  })
})

test('fails closed if Chromium does not close a page before the cleanup deadline', async () => {
  const { browser, state } = fakeBrowser({
    closePage: () => new Promise(() => {})
  })
  let fatalCalls = 0
  await withServer(createBpmnHandler({
    browser,
    closeDeadlineMs: 10,
    onFatal: () => { fatalCalls += 1 }
  }), async url => {
    const first = await post(url)
    assert.equal(first.status, 200)
    await new Promise(resolve => setTimeout(resolve, 25))
    const second = await post(url)
    assert.equal(second.status, 503)
    assert.equal(state.pages, 1)
    assert.equal(state.browserClosed, 1)
    assert.equal(fatalCalls, 1)
  })
})

test('kills Chromium if browser shutdown exceeds the cleanup deadline', async () => {
  const { browser, state } = fakeBrowser({
    closePage: () => new Promise(() => {}),
    closeBrowser: () => new Promise(() => {})
  })
  let fatalCalls = 0
  await withServer(createBpmnHandler({
    browser,
    closeDeadlineMs: 10,
    onFatal: () => { fatalCalls += 1 }
  }), async url => {
    const response = await post(url)
    assert.equal(response.status, 200)
    await new Promise(resolve => setTimeout(resolve, 35))
    assert.equal(state.browserKilled, true)
    assert.equal(fatalCalls, 1)
  })
})

test('rejects requests above the concurrent render limit and completes admitted renders', async () => {
  let releaseRendering
  let startedCount = 0
  let signalStarted
  const started = new Promise(resolve => { signalStarted = resolve })
  const gate = new Promise(resolve => { releaseRendering = resolve })
  const { browser } = fakeBrowser({
    setContent: async () => {
      startedCount += 1
      if (startedCount === 2) signalStarted()
      await gate
    }
  })

  await withServer(createBpmnHandler({ browser, maxConcurrent: 2, deadlineMs: 1000 }), async url => {
    const first = post(url)
    const second = post(url)
    await started
    const rejected = await post(url)
    assert.equal(rejected.status, 503)
    releaseRendering()
    const admitted = await Promise.all([first, second])
    assert.deepEqual(admitted.map(response => response.status), [200, 200])
  })
})
