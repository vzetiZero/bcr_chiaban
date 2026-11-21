// Cầu nối an toàn giữa renderer và main process (contextIsolation: true).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aibcr', {
  info: () => ipcRenderer.invoke('app:info'),
  call: (game, method, params) => ipcRenderer.invoke('engine:call', { game, method, params }),
  openProfiles: (count, siteId, profiles, source, omniApiUrl) => ipcRenderer.invoke('profiles:open',
    { count, siteId, profiles, source, omniApiUrl }),
  openProfile: (index, count, profile, url, source, omniApiUrl) => ipcRenderer.invoke('profile:open',
    { index, count, profile, url, source, omniApiUrl }),
  closeProfile: (index) => ipcRenderer.invoke('profile:close', { index }),
  closeProfiles: () => ipcRenderer.invoke('profiles:close'),
  listProxies: () => ipcRenderer.invoke('proxy:list'),
  importProxyText: (text) => ipcRenderer.invoke('proxy:import', { text }),
  removeProxy: (id) => ipcRenderer.invoke('proxy:remove', { id }),
  assignProxy: (profile, proxyId) => ipcRenderer.invoke('proxy:assign', { profile, proxyId }),
  checkProxies: () => ipcRenderer.invoke('proxy:check'),
  listOmniProfiles: (apiUrl) => ipcRenderer.invoke('omni:profiles', { apiUrl }),
  openDreamGaming: () => ipcRenderer.invoke('febet:open-dg'),
  autoRunFebet: () => ipcRenderer.invoke('febet:auto-run'),
  listFebetTables: () => ipcRenderer.invoke('febet:tables'),
  syncFebetTableById: (tableId) => ipcRenderer.invoke('febet:sync-table', { tableId }),
  getBetConfig: () => ipcRenderer.invoke('bets:config:get'),
  saveBetConfig: (config) => ipcRenderer.invoke('bets:config:save', { config }),
  applyBets: (tableId, tableIds) => ipcRenderer.invoke('bets:apply', { tableId, tableIds }),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  saveText: (name, text) => ipcRenderer.invoke('app:saveText', { name, text }),
  windowControl: (action) => ipcRenderer.send('window:control', action),
  onEngineEvent: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('engine:event', listener);
    return () => ipcRenderer.removeListener('engine:event', listener);
  },
  onGroupHop: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('group-hop', listener);
    return () => ipcRenderer.removeListener('group-hop', listener);
  },
});
