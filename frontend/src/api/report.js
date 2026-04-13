import api from './index.js'

export function generateReport(data) {
  return api.post('/report/generate', data)
}

export function getReportStatus(taskId) {
  return api.get(`/report/status/${taskId}`)
}

export function getReport(reportId) {
  return api.get(`/report/${reportId}`)
}

export function getReportBySimulation(simulationId) {
  return api.get(`/report/by-simulation/${simulationId}`)
}

export function chatWithReport(reportId, data) {
  return api.post(`/report/${reportId}/chat`, data)
}
