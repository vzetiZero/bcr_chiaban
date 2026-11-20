// Cầu nối an toàn giữa renderer và main process (contextIsolation: true).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aibcr', {
  info: () => ipcRenderer.invoke('app:info'),
  call: (game, method, params) => ipcRenderer.invoke('engine:call', { game, method, params }),
  openProfiles: (count, siteId, profiles) => ipcRenderer.invoke('profiles:open', { count, siteId, profiles }),
  openProfile: (index, count, profile, url) => ipcRenderer.invoke('profile:open', { index, count, profile, url }),
  closeProfile: (index) => ipcRenderer.invoke('profile:close', { index }),
  closeProfiles: () => ipcRenderer.invoke('profiles:close'),
  listProxies: () => ipcRenderer.invoke('proxy:list'),
  importProxyText: (text) => ipcRenderer.invoke('proxy:import', { text }),
  removeProxy: (id) => ipcRenderer.invoke('proxy:remove', { id }),
  assignProxy: (profile, proxyId) => ipcRenderer.invoke('proxy:assign', { profile, proxyId }),
  checkProxies: () => ipcRenderer.invoke('proxy:check'),
  openDreamGaming: () => ipcRenderer.invoke('febet:open-dg'),
  inspectFebet: () => ipcRenderer.invoke('febet:inspect'),
  selectFebetTable: (label) => ipcRenderer.invoke('febet:select-table', { label }),
  syncFebetTableById: (tableId) => ipcRenderer.invoke('febet:sync-table', { tableId }),
  applyBets: (amount, unit, split) => ipcRenderer.invoke('bets:apply', { amount, unit, split }),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  saveText: (name, text) => ipcRenderer.invoke('app:saveText', { name, text }),
  windowControl: (action) => ipcRenderer.send('window:control', action),
  onEngineEvent: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('engine:event', listener);
    return () => ipcRenderer.removeListener('engine:event', listener);
  },
});
