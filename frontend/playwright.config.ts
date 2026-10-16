import { defineConfig,devices } from '@playwright/test'
// Browser tests own and stop their Vite process. Keep it separate from the user's app.
const testPort=Number(process.env.E2E_PORT || 3100)
if(!Number.isInteger(testPort) || testPort<1024 || testPort>65535 || testPort===3000)throw new Error('Use a dedicated E2E port, separate from the application on 3000')
const testUrl=`http://127.0.0.1:${testPort}`
export default defineConfig({
 testDir:'./tests-e2e',fullyParallel:false,workers:1,timeout:45000,
 retries:process.env.CI?1:0,
 reporter:[['list'],['html',{outputFolder:'../temp/playwright-report',open:'never'}]],
 outputDir:'../temp/playwright-results',
 use:{baseURL:testUrl,trace:'retain-on-failure',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
 webServer:{command:`"${process.execPath}" node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${testPort} --strictPort`,url:testUrl,reuseExistingServer:!process.env.CI,timeout:60000}
})
