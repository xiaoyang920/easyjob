import { defineConfig,devices } from '@playwright/test'
export default defineConfig({
 testDir:'./tests-e2e',fullyParallel:false,workers:1,timeout:45000,
 retries:process.env.CI?1:0,
 reporter:[['list'],['html',{outputFolder:'../temp/playwright-report',open:'never'}]],
 outputDir:'../temp/playwright-results',
 use:{baseURL:'http://127.0.0.1:3000',trace:'retain-on-failure',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 3000',url:'http://127.0.0.1:3000',reuseExistingServer:!process.env.CI,timeout:60000}
})
