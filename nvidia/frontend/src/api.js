const API_BASE_URL = window.location.origin;

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP Error ${response.status}`);
  }
  
  return response.json();
}

export async function getHealth() {
  return request("/health");
}

export async function getSystemStatus() {
  return request("/system/status");
}

export async function getCameraStatus() {
  return request("/camera/status");
}

export async function getModelStatus() {
  return request("/model/status");
}

export async function login(username, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function startInference() {
  return request("/inference/start", { method: "POST" });
}

export async function stopInference() {
  return request("/inference/stop", { method: "POST" });
}

export async function getInferenceStatus() {
  return request("/inference/status");
}
