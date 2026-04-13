import api from './index.js'

export function generateOntology(formData) {
  return api.post('/graph/ontology/generate', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function buildGraph(data) {
  return api.post('/graph/build', data)
}

export function getTaskStatus(taskId) {
  return api.get(`/graph/task/${taskId}`)
}

export function getGraphData(graphId) {
  return api.get(`/graph/data/${graphId}`)
}

export function getProject(projectId) {
  return api.get(`/graph/project/${projectId}`)
}

export function listProjects() {
  return api.get('/graph/project/list')
}
