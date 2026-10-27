// @todo #TD-025:1d Расширить проверки обработки диаграмм
// refs: .tasks/TD-025.md
// scope: .tools/plantuml-render
// type: test
export const MAX_BODY_BYTES = 2 * 1024 * 1024
export const MAX_DIMENSION = 8192
export const MAX_PIXELS = 16_777_216
export const MAX_CONCURRENT_RENDERS = 2
export const RENDER_DEADLINE_MS = 10_000

class HttpError extends Error {
  constructor(statusCode, message) {
    super(message)
    this.statusCode = statusCode
  }
}

function rejectAndClose(request, response, statusCode, message) {
  if (response.destroyed || response.writableEnded) return
  response.shouldKeepAlive = false
  response.writeHead(statusCode, {
    'Connection': 'close',
    'Content-Type': 'text/plain; charset=utf-8'
  })
  response.end(message, () => {
    if (!request.complete && !request.destroyed) request.destroy()
  })
}

export function validateDimensions(size, maxDimension = MAX_DIMENSION, maxPixels = MAX_PIXELS) {
  const width = Math.ceil(Number(size?.width))
  const height = Math.ceil(Number(size?.height))
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new HttpError(400, 'SVG dimensions must be finite positive numbers.')
  }
  if (width > maxDimension || height > maxDimension || width * height > maxPixels) {
    throw new HttpError(400, 'SVG dimensions exceed the rasterizer limits.')
  }
  return { width, height }
}

export function readRequestBody(request, maxBytes = MAX_BODY_BYTES) {
  const contentEncoding = request.headers['content-encoding']
  if (contentEncoding && contentEncoding !== 'identity') {
    request.pause()
    return Promise.reject(new HttpError(415, 'Compressed request bodies are not supported.'))
  }
  const declaredLength = Number(request.headers['content-length'])
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    request.pause()
    return Promise.reject(new HttpError(413, 'SVG request body exceeds the size limit.'))
  }

  return new Promise((resolve, reject) => {
    const chunks = []
    let totalBytes = 0
    let settled = false
    const cleanup = () => {
      request.removeListener('data', onData)
      request.removeListener('end', onEnd)
      request.removeListener('error', onError)
      request.removeListener('aborted', onAborted)
    }
    const fail = error => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }
    const onData = chunk => {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
      totalBytes += buffer.length
      if (totalBytes > maxBytes) {
        request.pause()
        fail(new HttpError(413, 'SVG request body exceeds the size limit.'))
        return
      }
      chunks.push(buffer)
    }
    const onEnd = () => {
      if (settled) return
      settled = true
      cleanup()
      resolve(Buffer.concat(chunks, totalBytes).toString('utf8'))
    }
    const onError = error => fail(error)
    const onAborted = () => fail(new HttpError(400, 'SVG request body was interrupted.'))

    request.on('data', onData)
    request.once('end', onEnd)
    request.once('error', onError)
    request.once('aborted', onAborted)
  })
}

async function runWithDeadline(operation, deadline) {
  const remaining = deadline - Date.now()
  if (remaining <= 0) throw new HttpError(504, 'Rasterization deadline exceeded.')
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new HttpError(504, 'Rasterization deadline exceeded.')), remaining)
  })
  try {
    return await Promise.race([Promise.resolve().then(operation), timeout])
  } finally {
    clearTimeout(timer)
  }
}

async function closePage(page, closeDeadlineMs = 1000) {
  if (!page) return true
  let timer
  try {
    return await Promise.race([
      Promise.resolve().then(() => page.close()).then(() => true, () => false),
      new Promise(resolve => {
        timer = setTimeout(() => resolve(false), closeDeadlineMs)
      })
    ])
  } finally {
    clearTimeout(timer)
  }
}

async function closeBrowser(browser, closeDeadlineMs) {
  try {
    await runWithDeadline(() => browser.close(), Date.now() + closeDeadlineMs)
    return
  } catch {
    try {
      const child = browser.process?.()
      if (child && !child.killed) child.kill('SIGKILL')
    } catch {
      // Завершение процесса сервиса ниже остаётся последним ограничителем.
    }
  }
}

export function createBpmnHandler({
  browser,
  maxBodyBytes = MAX_BODY_BYTES,
  maxDimension = MAX_DIMENSION,
  maxPixels = MAX_PIXELS,
  maxConcurrent = MAX_CONCURRENT_RENDERS,
  deadlineMs = RENDER_DEADLINE_MS,
  closeDeadlineMs = 1000,
  onFatal = () => {}
}) {
  let active = 0
  let unhealthy = false
  let termination

  function terminateUnhealthyBrowser() {
    if (termination) return termination
    unhealthy = true
    termination = (async () => {
      await closeBrowser(browser, closeDeadlineMs)
      onFatal()
    })()
    return termination
  }

  return async (request, response) => {
    if (request.method !== 'POST' || request.url !== '/rasterize') {
      rejectAndClose(request, response, 404, '')
      return
    }
    if (unhealthy) {
      rejectAndClose(request, response, 503, 'Rasterizer is unavailable. Restart the service.')
      return
    }
    if (active >= maxConcurrent) {
      rejectAndClose(request, response, 503, 'Rasterizer is busy. Retry later.')
      return
    }

    active += 1
    let page
    try {
      const svg = await readRequestBody(request, maxBodyBytes)
      if (!svg.trim()) throw new HttpError(400, 'SVG body must not be empty.')

      const deadline = Date.now() + deadlineMs
      const pendingPage = Promise.resolve().then(() => browser.newPage())
      try {
        page = await runWithDeadline(() => pendingPage, deadline)
      } catch (error) {
        void terminateUnhealthyBrowser()
        throw error
      }

      await runWithDeadline(() => page.setRequestInterception(true), deadline)
      page.on('request', interceptedRequest => interceptedRequest.abort())
      const contentSecurityPolicy = [
        "default-src 'none'",
        "script-src 'none'",
        "connect-src 'none'",
        "img-src data: blob:",
        "style-src 'unsafe-inline'",
        "font-src data:"
      ].join('; ')
      const html = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy}"></head><body style="margin:0">${svg}</body></html>`
      await runWithDeadline(
        () => page.setContent(html, { timeout: Math.max(1, deadline - Date.now()) }),
        deadline
      )
      const rawSize = await runWithDeadline(
        () => page.$eval('svg', element => {
          const bounds = element.getBoundingClientRect()
          return { width: bounds.width, height: bounds.height }
        }),
        deadline
      )
      const size = validateDimensions(rawSize, maxDimension, maxPixels)
      await runWithDeadline(
        () => page.setViewport({ width: size.width, height: size.height, deviceScaleFactor: 1 }),
        deadline
      )
      const png = await runWithDeadline(
        () => page.screenshot({
          type: 'png',
          clip: { x: 0, y: 0, width: size.width, height: size.height }
        }),
        deadline
      )
      response.writeHead(200, { 'Content-Type': 'image/png' })
      response.end(png)
    } catch (error) {
      const statusCode = Number.isInteger(error?.statusCode) ? error.statusCode : 500
      const message = statusCode === 500 ? 'Unable to rasterize SVG.' : error.message
      rejectAndClose(request, response, statusCode, message)
    } finally {
      if (!await closePage(page, closeDeadlineMs)) {
        await terminateUnhealthyBrowser()
      }
      active -= 1
    }
  }
}
