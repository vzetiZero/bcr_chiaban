// Cầu nối an toàn giữa renderer và main process (contextIsolation: true).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aibcr', {
  info: () => ipcRenderer.invoke('app:info'),
  call: (game, method, params) => ipcRenderer.invoke('engine:call', { game, method, params }),
  openProfiles: (count, siteId, profiles) => ipcRenderer.invoke('profiles:open', { count, siteId, profiles }),
  openProfile: (index, count, profile) => ipcRenderer.invoke('profile:open', { index, count, profile }),
  closeProfile: (index) => ipcRenderer.invoke('profile:close', { index }),
  closeProfiles: () => ipcRenderer.invoke('profiles:close'),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  saveText: (name, text) => ipcRenderer.invoke('app:saveText', { name, text }),
  windowControl: (action) => ipcRenderer.send('window:control', action),
  onEngineEvent: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('engine:event', listener);
    return () => ipcRenderer.removeListener('engine:event', listener);
  },
});
