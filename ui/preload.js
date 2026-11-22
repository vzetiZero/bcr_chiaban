// Cầu nối an toàn giữa renderer và main process (contextIsolation: true).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aibcr', {
  info: () => ipcRenderer.invoke('app:info'),
  call: (game, method, params) => ipcRenderer.invoke('engine:call', { game, method, params }),
  listSites: () => ipcRenderer.invoke('sites:list'),
  createSite: (site) => ipcRenderer.invoke('sites:create', { site }),
  updateSite: (site) => ipcRenderer.invoke('sites:update', { site }),
  deleteSite: (id) => ipcRenderer.invoke('sites:delete', { id }),
  resetSites: () => ipcRenderer.invoke('sites:reset'),
  getProfileFingerprint: (index) => ipcRenderer.invoke('profile:fingerprint', { index }),
  regenerateProfileFingerprint: (index) => ipcRenderer.invoke('profile:regenerateFingerprint', { index }),
  loadProfileConnections: () => ipcRenderer.invoke('profiles:connections'),
  forgetProfileConnection: (index) => ipcRenderer.invoke('profiles:forgetConnection', { index }),
  openProfiles: (count, siteId, profiles, source, omniApiUrl, siteIds, hidemiumApiUrl, indices) => ipcRenderer.invoke('profiles:open',
    { count, siteId, profiles, source, omniApiUrl, siteIds, hidemiumApiUrl, indices }),
  openProfile: (index, count, profile, url, source, omniApiUrl, hidemiumApiUrl) => ipcRenderer.invoke('profile:open',
    { index, count, profile, url, source, omniApiUrl, hidemiumApiUrl }),
  closeProfile: (index) => ipcRenderer.invoke('profile:close', { index }),
  closeProfiles: () => ipcRenderer.invoke('profiles:close'),
  listProxies: () => ipcRenderer.invoke('proxy:list'),
  importProxyText: (text) => ipcRenderer.invoke('proxy:import', { text }),
  removeProxy: (id) => ipcRenderer.invoke('proxy:remove', { id }),
  assignProxy: (profile, proxyId) => ipcRenderer.invoke('proxy:assign', { profile, proxyId }),
  checkProxies: () => ipcRenderer.invoke('proxy:check'),
  listOmniProfiles: (apiUrl) => ipcRenderer.invoke('omni:profiles', { apiUrl }),
  listHidemiumProfiles: (apiUrl) => ipcRenderer.invoke('hidemium:profiles', { apiUrl }),
  openDreamGaming: () => ipcRenderer.invoke('febet:open-dg'),
  autoRunFebet: () => ipcRenderer.invoke('febet:auto-run'),
  runDGGroup: (count, siteIds, indices) => ipcRenderer.invoke('dg:auto-run', { count, siteIds, indices }),
  listFebetTables: () => ipcRenderer.invoke('febet:tables'),
  syncFebetTableById: (tableId) => ipcRenderer.invoke('febet:sync-table', { tableId }),
  getBetConfig: () => ipcRenderer.invoke('bets:config:get'),
  saveBetConfig: (config) => ipcRenderer.invoke('bets:config:save', { config }),
  getActivityLog: () => ipcRenderer.invoke('activity-log:get'),
  clearActivityLog: () => ipcRenderer.invoke('activity-log:clear'),
  applyBets: (tableId, tableIds) => ipcRenderer.invoke('bets:apply', { tableId, tableIds }),
  startBetsOnOpenProfiles: (config) => ipcRenderer.invoke('bets:start-open', { config }),
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
  onActivityLogEntry: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('activity-log:entry', listener);
    return () => ipcRenderer.removeListener('activity-log:entry', listener);
  },
  onActivityLogClear: (handler) => {
    const listener = () => handler();
    ipcRenderer.on('activity-log:clear', listener);
    return () => ipcRenderer.removeListener('activity-log:clear', listener);
  },
});
