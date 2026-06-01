import React, { useState, useEffect, useRef } from "react";
import { 
  Activity, Cpu, HardDrive, Thermometer, Play, Square, 
  LogOut, Lock, User, Server, Camera, ShieldAlert, Zap
} from "lucide-react";
import * as api from "./api";
import logoImg from "./assets/logo.png";

export default function App() {
  // Authentication State
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem("nv_user");
    return saved ? JSON.parse(saved) : null;
  });
  const [loginError, setLoginError] = useState("");

  // Health Diagnostics (Login screen and Dashboard header)
  const [health, setHealth] = useState({
    backend: "offline",
    model: "not_loaded",
    camera: "offline"
  });

  // System & Model Telemetry
  const [telemetry, setTelemetry] = useState({
    cpu_percent: 0,
    memory: { total_gb: 8.0, used_gb: 0, percent: 0 },
    disk: { total_gb: 128.0, used_gb: 0, free_gb: 0, percent: 0 },
    temperatures: { cpu: 0.0, gpu: 0.0, is_mock: true },
    power: { current_w: 4.1, max_w: 15.0, percent: 27.3 },
    platform: "unknown"
  });
  
  const [modelStatus, setModelStatus] = useState({
    loaded: false,
    model_name: "unknown",
    version: "0.0.0",
    backend: "none"
  });

  const modelBackendRef = useRef("none");
  useEffect(() => {
    modelBackendRef.current = modelStatus.backend;
  }, [modelStatus.backend]);

  const [inferenceRunning, setInferenceRunning] = useState(false);

  // --- Background Diagnostics Check (Runs always) ---
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const data = await api.getHealth();
        setHealth({
          backend: data.backend,
          model: data.model,
          camera: data.camera
        });
      } catch (err) {
        setHealth({
          backend: "offline",
          model: "not_loaded",
          camera: "offline"
        });
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 3000);
    return () => clearInterval(interval);
  }, []);

  // --- Dashboard Data Polling (Runs when logged in) ---
  useEffect(() => {
    if (!user) return;

    // Load Model Info once on login
    const loadModelInfo = async () => {
      try {
        const data = await api.getModelStatus();
        setModelStatus(data);
      } catch (err) {
        console.error("無法加載模型配置", err);
      }
    };
    loadModelInfo();

    // Check inference state
    const checkInference = async () => {
      try {
        const status = await api.getInferenceStatus();
        setInferenceRunning(status.inference_running);
      } catch (err) {
        console.error("無法讀取推理狀態", err);
      }
    };
    checkInference();

    // Polling Telemetry Data
    const pollTelemetry = async () => {
      try {
        const data = await api.getSystemStatus();
        setTelemetry(data);
        
        // 自動重連：如果當前模型後端為 none，且後端此時能正常拉取數據，就自動重新加載模型資訊
        if (modelBackendRef.current === "none" || modelBackendRef.current === "unknown") {
          try {
            const mData = await api.getModelStatus();
            setModelStatus(mData);
          } catch (e) {
            // ignore
          }
        }
      } catch (err) {
        console.error("無法拉取系統監控數據", err);
      }
    };
    
    pollTelemetry();
    const interval = setInterval(pollTelemetry, 1500);
    return () => clearInterval(interval);
  }, [user]);



  // --- Event Handlers ---
  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError("");
    try {
      // Direct login: automatically authenticate using default admin account
      const data = await api.login("admin", "admin123");
      if (data.success) {
        setUser(data.user);
        localStorage.setItem("nv_user", JSON.stringify(data.user));
      }
    } catch (err) {
      setLoginError(err.message || "登入失敗，請確認後端服務運作正常");
    }
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem("nv_user");
    setLoginError("");
  };

  const handleStartInference = async () => {
    try {
      const res = await api.startInference();
      if (res.status === "success") {
        setInferenceRunning(true);
      }
    } catch (err) {
      console.error("無法啟動推理引擎", err);
    }
  };

  const handleStopInference = async () => {
    try {
      const res = await api.stopInference();
      if (res.status === "success") {
        setInferenceRunning(false);
      }
    } catch (err) {
      console.error("無法停止推理引擎", err);
    }
  };

  // --- Render Functions ---
  const renderLogin = () => (
    <div className="login-wrapper">
      <div className="login-card glass-panel">
        <div className="login-header">
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '1.5rem' }}>
            <img src={logoImg} alt="Logo" style={{ height: '55px', objectFit: 'contain', filter: 'drop-shadow(0 0 8px rgba(255,255,255,0.15))' }} />
          </div>
          <h1>NVIDIA 邊緣 AI 控制面板</h1>
          <p>系統診斷正常，請點擊下方按鈕進入控制面板</p>
        </div>

        {loginError && <div className="error-banner">{loginError}</div>}

        {/* Diagnostic Bar before Login */}
        <div className="diagnostics-bar">
          <div className="diag-item">
            <Server size={16} />
            <span>後端服務</span>
            <div className={`status-dot ${health.backend === "online" ? "online" : "offline"}`} />
          </div>
          <div className="diag-item">
            <Activity size={16} />
            <span>AI 模型</span>
            <div className={`status-dot ${health.model === "loaded" ? "online" : "offline"}`} />
          </div>
          <div className="diag-item">
            <Camera size={16} />
            <span>影像相機</span>
            <div className={`status-dot ${
              health.camera === "connected" ? "online" : (health.camera === "simulated" ? "simulated" : "offline")
            }`} />
          </div>
        </div>

        <form onSubmit={handleLogin}>
          <button type="submit" className="login-btn">進入系統</button>
        </form>
      </div>
    </div>
  );

  const renderDashboard = () => (
    <div className="dashboard-grid">
      {/* Main column: Video stream & controls */}
      <div className="main-column">
        {/* Video Card */}
        <div className="video-card glass-panel">
          <div className="card-header">
            <div className="card-title-group">
              <Camera size={20} color="var(--nv-green)" />
              <span className="card-title">即時影像監控</span>
            </div>
            {health.camera === "simulated" && (
              <span className="system-mode-tag" style={{ color: '#f59e0b', borderColor: 'rgba(245,158,11,0.3)', background: 'rgba(245,158,11,0.1)' }}>
                模擬影像源
              </span>
            )}
          </div>
          
          <div className={`video-container ${inferenceRunning ? "active" : "paused"}`}>
            {health.backend === "online" ? (
              <img 
                src="http://127.0.0.1:8000/video_feed" 
                alt="AI Video Stream" 
                className="stream-image"
                onError={(e) => {
                  e.target.style.display = 'none';
                  e.target.nextSibling.style.display = 'flex';
                }}
              />
            ) : null}
            <div className="stream-placeholder" style={{ display: health.backend === "online" ? 'none' : 'flex' }}>
              <ShieldAlert size={48} color="var(--status-offline)" />
              <span>無法載入視訊源，請檢查後端服務通訊。</span>
            </div>
            
            <div className="overlay-badge">
              <div className={`status-dot ${inferenceRunning ? "online" : "simulated"}`} />
              <span>{inferenceRunning ? "AI 偵測中" : "暫停偵測"}</span>
            </div>
          </div>
        </div>

        {/* Control Card */}
        <div className="control-card glass-panel">
          <div className="card-header">
            <div className="card-title-group">
              <Activity size={20} color="var(--nv-green)" />
              <span className="card-title">AI 推理控制面板</span>
            </div>
          </div>
          <div className="control-buttons-group">
            <button 
              className="ctrl-btn start" 
              onClick={handleStartInference}
              disabled={inferenceRunning}
            >
              <Play size={16} /> 啟動 AI 影像偵測
            </button>
            <button 
              className="ctrl-btn stop" 
              onClick={handleStopInference}
              disabled={!inferenceRunning}
            >
              <Square size={16} /> 停止偵測任務
            </button>
          </div>
        </div>
      </div>

      {/* Side column: Telemetry stats & Logs */}
      <div className="side-column">
        {/* Telemetry Card */}
        <div className="telemetry-card glass-panel">
          <div className="card-header">
            <div className="card-title-group">
              <Cpu size={20} color="var(--nv-green)" />
              <span className="card-title">硬體 Telemetry 監控</span>
            </div>
          </div>
          
          <div className="telemetry-grid">
            <div className="stat-box">
              <div className="stat-label">
                <Cpu size={14} /> CPU 使用率
              </div>
              <div className="stat-value">{telemetry.cpu_percent}%</div>
              <div className="progress-track">
                <div 
                  className={`progress-bar ${telemetry.cpu_percent > 85 ? "danger" : (telemetry.cpu_percent > 65 ? "warning" : "")}`} 
                  style={{ width: `${telemetry.cpu_percent}%` }}
                />
              </div>
            </div>

            <div className="stat-box">
              <div className="stat-label">
                <HardDrive size={14} /> 記憶體 (RAM)
              </div>
              <div className="stat-value">{telemetry.memory.percent}%</div>
              <div className="progress-track">
                <div 
                  className={`progress-bar ${telemetry.memory.percent > 85 ? "danger" : (telemetry.memory.percent > 65 ? "warning" : "")}`} 
                  style={{ width: `${telemetry.memory.percent}%` }}
                />
              </div>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
                {telemetry.memory.used_gb} / {telemetry.memory.total_gb} GB
              </span>
            </div>

            <div className="stat-box">
              <div className="stat-label">
                <HardDrive size={14} /> 儲存空間 (Disk)
              </div>
              <div className="stat-value">{telemetry.disk.percent}%</div>
              <div className="progress-track">
                <div 
                  className={`progress-bar ${telemetry.disk.percent > 90 ? "danger" : ""}`} 
                  style={{ width: `${telemetry.disk.percent}%` }}
                />
              </div>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
                已用: {telemetry.disk.used_gb} GB / 剩餘: {telemetry.disk.free_gb} GB
              </span>
            </div>

            <div className="stat-box">
              <div className="stat-label">
                <Thermometer size={14} /> GPU 溫度
              </div>
              <div className="stat-value">{telemetry.temperatures.gpu} °C</div>
              <div className="progress-track">
                <div 
                  className={`progress-bar ${telemetry.temperatures.gpu > 75 ? "danger" : (telemetry.temperatures.gpu > 60 ? "warning" : "")}`} 
                  style={{ width: `${Math.min(100, (telemetry.temperatures.gpu / 90) * 100)}%` }}
                />
              </div>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                CPU 溫度: {telemetry.temperatures.cpu} °C
              </span>
            </div>

            <div className="stat-box">
              <div className="stat-label">
                <Zap size={14} /> 系統功耗 (Power)
              </div>
              <div className="stat-value">{telemetry.power?.current_w || 0} W</div>
              <div className="progress-track">
                <div 
                  className={`progress-bar ${telemetry.power?.current_w > 12.0 ? "warning" : ""}`} 
                  style={{ width: `${telemetry.power?.percent || 0}%` }}
                />
              </div>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
                最大限制: {telemetry.power?.max_w || 15.0} W
              </span>
            </div>
          </div>
        </div>

        {/* Model Specs Card */}
        <div className="specs-card glass-panel">
          <div className="specs-horizontal">
            <div className="specs-title">
              <Activity size={14} color="var(--nv-green)" />
              <span>模型規格</span>
            </div>
            <div className="specs-items">
              <div className="specs-item">
                <span className="specs-label">版本:</span>
                <span className="specs-val">{modelStatus.version}</span>
              </div>
              <div className="specs-item">
                <span className="specs-label">解析度:</span>
                <span className="specs-val">
                  {modelStatus.input_size ? `${modelStatus.input_size[0]}x${modelStatus.input_size[1]}` : "N/A"}
                </span>
              </div>
              <div className="specs-item">
                <span className="specs-label">後端:</span>
                <span className="specs-val active-backend">{modelStatus.backend}</span>
              </div>
            </div>
          </div>
        </div>


      </div>
    </div>
  );

  return (
    <div className="app-container">
      {/* Header bar */}
      <header className="header">
        <div className="brand-section">
          <div className="brand-logo-glow" />
          <span className="brand-title">NVIDIA System Interface Board</span>
          <span className="system-mode-tag">開發版 v1.1</span>
        </div>
        
        {user ? (
          <div className="user-panel">
            {health.backend === "offline" && (
              <span className="conn-warning-tag" style={{
                color: 'var(--status-offline)',
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.3)',
                padding: '4px 10px',
                borderRadius: '20px',
                fontSize: '0.75rem',
                fontWeight: '600',
                marginRight: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}>
                ⚠️ 服務中斷
              </span>
            )}
            <div className="user-info">
              <div style={{ fontWeight: '600' }}>{user.username}</div>
              <div className="user-role">{user.role}</div>
            </div>
            <button className="logout-btn" onClick={handleLogout}>登出系統</button>
          </div>
        ) : (
          <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            系統狀態: {health.backend === "online" ? "🟢 後端已連線" : "🔴 後端離線"}
          </span>
        )}
      </header>

      {/* Main Content Area */}
      {user ? renderDashboard() : renderLogin()}
    </div>
  );
}
