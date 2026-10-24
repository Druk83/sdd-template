import http from 'node:http'
import puppeteer from 'puppeteer'
import { createBpmnHandler } from './bpmn-png-handler.mjs'

const port = Number(process.env.PORT || 8001)
const host = process.env.HOST || '0.0.0.0'

const browser = await puppeteer.launch({
  args: [
    '--disable-gpu',
    '--headless',
    '--hide-scrollbars',
    '--no-sandbox'
  ]
})

const server = http.createServer(createBpmnHandler({
  browser,
  onFatal: () => {
    process.stderr.write('Chromium cleanup failed; restarting the rasterizer service.\n')
    setTimeout(() => process.exit(1), 100)
  }
}))
server.requestTimeout = 15_000
server.headersTimeout = 10_000

server.listen(port, host)
