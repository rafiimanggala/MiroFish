import api from './index.js'

export function createSimulation(data) {
  return api.post('/simulation/create', data)
}

export function startSimulation(simulationId) {
  return api.post(`/simulation/${simulationId}/start`)
}

export function stopSimulation(simulationId) {
  return api.post(`/simulation/${simulationId}/stop`)
}

export function getSimulation(simulationId) {
  return api.get(`/simulation/${simulationId}`)
}

export function getSimulationActions(simulationId, params = {}) {
  return api.get(`/simulation/${simulationId}/actions`, { params })
}

export function getSimulationTimeline(simulationId) {
  return api.get(`/simulation/${simulationId}/timeline`)
}

export function getAgentStats(simulationId) {
  return api.get(`/simulation/${simulationId}/agent-stats`)
}

export function interviewAgent(simulationId, data) {
  return api.post(`/simulation/${simulationId}/interview`, data)
}
