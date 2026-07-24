import http from 'node:http'
import puppeteer from 'puppeteer'

const port = Number(process.env.PORT || 8001)

const browser = await puppeteer.launch({
  args: [
    '--disable-gpu',
    '--headless',
    '--hide-scrollbars',
    '--no-sandbox'
  ]
})

const server = http.createServer(async (request, response) => {
  if (request.method !== 'POST' || request.url !== '/rasterize') {
    response.writeHead(404)
    response.end()
    return
  }

  try {
    const chunks = []
    for await (const chunk of request) {
      chunks.push(chunk)
    }
    const svg = Buffer.concat(chunks).toString('utf8')
    if (!svg) {
      response.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' })
      response.end('SVG body must not be empty.')
      return
    }

    const page = await browser.newPage()
    try {
      await page.setContent(`<!doctype html><html><body style="margin:0">${svg}</body></html>`)
      const size = await page.$eval('svg', element => {
        const bounds = element.getBoundingClientRect()
        return {
          width: Math.ceil(bounds.width),
          height: Math.ceil(bounds.height)
        }
      })
      if (size.width <= 0 || size.height <= 0) {
        throw new Error('SVG dimensions must be greater than zero.')
      }
      await page.setViewport({ width: size.width, height: size.height, deviceScaleFactor: 1 })
      const png = await page.screenshot({
        type: 'png',
        clip: { x: 0, y: 0, width: size.width, height: size.height }
      })
      response.writeHead(200, { 'Content-Type': 'image/png' })
      response.end(png)
    } finally {
      await page.close()
    }
  } catch (error) {
    response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end(error.message)
  }
})

server.listen(port)
