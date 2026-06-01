import asyncio
from playwright.async_api import async_playwright
import os
import time

async def main():
    async with async_playwright() as p:
        # Launch browser pointing to our symlinked Chromium path
        browser = await p.chromium.launch(
            executable_path="/home/user/.local/bin/google-chrome",
            headless=True
        )
        page = await browser.new_page()
        
        print("正在開啟網頁 http://localhost:5173/ ...")
        await page.goto("http://localhost:5173/")
        await page.wait_for_timeout(2000)
        
        # Take login page screenshot
        login_img = "/home/user/workspace/login_page.png"
        await page.screenshot(path=login_img)
        print(f"登入頁面截圖已儲存至: {login_img}")
        
        # Click login button
        print("點擊 '進入系統' 按鈕...")
        await page.click("button.login-btn")
        await page.wait_for_timeout(3000)
        
        # Take dashboard screenshot
        dashboard_img = "/home/user/workspace/dashboard_page.png"
        await page.screenshot(path=dashboard_img)
        print(f"儀表板頁面截圖已儲存至: {dashboard_img}")
        
        # Click Start Detection button
        print("點擊 '啟動 AI 影像偵測' 按鈕...")
        await page.click("button.ctrl-btn.start")
        await page.wait_for_timeout(3000)
        
        # Take active detection screenshot
        active_img = "/home/user/workspace/active_detection.png"
        await page.screenshot(path=active_img)
        print(f"啟動偵測後的儀表板截圖已儲存至: {active_img}")
        
        # Click Stop Detection button
        print("點擊 '停止偵測任務' 按鈕...")
        await page.click("button.ctrl-btn.stop")
        await page.wait_for_timeout(1000)
        
        # Take stopped detection screenshot
        stopped_img = "/home/user/workspace/stopped_detection.png"
        await page.screenshot(path=stopped_img)
        print(f"停止偵測後的儀表板截圖已儲存至: {stopped_img}")
        
        await browser.close()
        print("測試與截圖完成！")

if __name__ == "__main__":
    asyncio.run(main())
