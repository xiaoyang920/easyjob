import { createPublicKey } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const [site, publicKeyFile, output] = process.argv.slice(2)
if (!site || !publicKeyFile || !output) {
  console.error('Usage: node browser-extension/configure.mjs https://example.org public-key.pem /path/to/copied-extension')
  process.exit(1)
}
const url = new URL(site)
if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
  throw new Error('Supply the HTTPS origin of the EasyJob deployment.')
}
const manifestPath = resolve(output, 'manifest.json')
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
manifest.externally_connectable = { matches: [`https://${url.hostname}/*`] }
manifest.key = createPublicKey(readFileSync(publicKeyFile)).export({ type: 'spki', format: 'der' }).toString('base64')
const workerPath = resolve(output, 'worker.js')
const worker = readFileSync(workerPath, 'utf8')
const deploymentOrigin = /^const DEPLOYMENT_ORIGIN = .*$/m
if (!deploymentOrigin.test(worker)) throw new Error('Missing deployment origin in worker.js')
writeFileSync(workerPath, worker.replace(deploymentOrigin, 'const DEPLOYMENT_ORIGIN = ' + JSON.stringify(url.origin)))
writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n')
