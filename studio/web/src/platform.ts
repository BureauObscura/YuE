const agent=typeof navigator==='undefined'?'':navigator.userAgent;

export const isWindows=/Windows/i.test(agent);
export const isMac=/Macintosh|Mac OS X/i.test(agent);
export const computerName=isWindows?'This PC':isMac?'This Mac':'This computer';
export const storedHere=isWindows?'Stored on this PC':isMac?'Stored on your Mac':'Stored on this computer';
export const shortcutModifier=isMac?'⌘':'Ctrl';
export const pythonPlaceholder=isWindows?'C:\\path\\to\\YuE\\.venv\\Scripts\\python.exe':'/path/to/YuE/.venv/bin/python';
export const installCommands=isWindows
 ? 'py -3.12 -m venv .venv\n.venv\\Scripts\\python.exe -m pip install .\n.venv\\Scripts\\python.exe -m pip install --force-reinstall --no-deps torch==2.10.0+cu130 --index-url https://download.pytorch.org/whl/cu130'
 : 'python3.12 -m venv .venv\n.venv/bin/python -m pip install .';
