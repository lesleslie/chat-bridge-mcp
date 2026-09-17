// Headless Electron fixture for chat-bridge-mcp e2e tests.
//
// Serves a minimal chat-like page on the Chromium DevTools Protocol port
// 9230 (pinned via the package.json `start` script and the
// commandLine.appendSwitch below). The page exposes:
//   - a textarea the bridge can type into (#prompt-textarea)
//   - a send button the bridge can click
//   - an assistant response container ([data-message-author-role=assistant])
//   - a window.__emitSend handler that, on send, writes 'pong' into the
//     assistant container — sufficient for the React-setter smoke test.
//
// CDP attach point: ws://127.0.0.1:9230/<target-id>
const { app, BrowserWindow } = require('electron');

app.commandLine.appendSwitch('remote-debugging-port', '9230');
app.commandLine.appendSwitch('disable-gpu');

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 800,
    height: 600,
    show: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });

  win.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent(`
        <html>
          <body>
            <textarea id="prompt-textarea" data-testid="prompt-textarea"></textarea>
            <button data-testid="send-button" onclick="window.__emitSend()">Send</button>
            <div data-message-author-role="assistant"></div>
            <script>
              window.__emitSend = async () => {
                const streamTarget = document.querySelector('[data-message-author-role="assistant"]');
                streamTarget.innerText = 'pong';
              };
            </script>
          </body>
        </html>
      `),
  );
});

// Quit when all windows are closed.
app.on('window-all-closed', () => app.quit());