//! 启动 / 停止片刻 Python（Flask）后端。

use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const DEFAULT_PORT: u16 = 5057;
const PORT_TRIES: u16 = 20;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);

pub struct Backend {
    #[allow(dead_code)]
    pub root: PathBuf,
    pub port: u16,
    child: Mutex<Option<Child>>,
}

impl Backend {
    pub fn start_at(root: PathBuf) -> Result<Self, String> {
        if !root.join("app.py").is_file() {
            return Err(format!("未找到 app.py：{}", root.join("app.py").display()));
        }

        let port = pick_port(DEFAULT_PORT)?;
        let mut cmd = build_backend_command(&root, port)?;
        apply_backend_env(&mut cmd);

        let mut child = cmd.spawn().map_err(|e| {
            format!(
                "无法启动 Python 后端：{}\n请先执行: make setup  或  uv sync --extra expert --extra tycoon",
                e
            )
        })?;

        if !wait_for_server(port, STARTUP_TIMEOUT) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "Flask 服务在 {} 秒内未在 127.0.0.1:{} 就绪，请查看终端日志。",
                STARTUP_TIMEOUT.as_secs(),
                port
            ));
        }

        Ok(Self {
            root,
            port,
            child: Mutex::new(Some(child)),
        })
    }

    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    pub fn stop(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        self.stop();
    }
}

/// 解析片刻项目根目录（含 app.py）。
pub fn find_pianke_root() -> Result<PathBuf, String> {
    if let Ok(root) = std::env::var("PIANKE_ROOT") {
        let p = PathBuf::from(root);
        if p.join("app.py").is_file() {
            return Ok(p);
        }
        return Err(format!("PIANKE_ROOT 无效（缺少 app.py）：{}", p.display()));
    }

    if let Some(root) = debug_repo_root() {
        return Ok(root);
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidates = [
                dir.join("pianke"),
                dir.join("../Resources/pianke"),
                dir.join("../../Resources/pianke"),
                dir.join("../pianke"),
            ];
            for candidate in candidates {
                let path = candidate
                    .canonicalize()
                    .unwrap_or_else(|_| candidate.clone());
                if path.join("app.py").is_file() {
                    return Ok(path);
                }
            }
        }
    }

    Err(
        "找不到片刻项目根目录（app.py）。\n\
         请先运行启动脚本安装依赖，或设置 PIANKE_ROOT=/path/to/pianke"
            .to_string(),
    )
}

/// 打包后从 Tauri 资源目录解析 pianke 根路径。
pub fn find_pianke_root_from_resource(
    resource_app_py: Result<PathBuf, tauri::Error>,
) -> Option<PathBuf> {
    if let Ok(app_py) = resource_app_py {
        return app_py.parent().map(Path::to_path_buf);
    }
    None
}

fn find_uv() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("UV") {
        let path = PathBuf::from(&p);
        if path.is_file() {
            return Some(path);
        }
    }
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"));
    let mut candidates: Vec<PathBuf> = vec![PathBuf::from(if cfg!(windows) {
        "uv.exe"
    } else {
        "uv"
    })];
    if let Some(h) = home {
        let h = PathBuf::from(h);
        candidates.push(h.join(".local/bin/uv"));
        candidates.push(h.join(".cargo/bin/uv"));
        #[cfg(windows)]
        candidates.push(h.join(".local/bin/uv.exe"));
    }
    for c in candidates {
        if c.is_file() {
            return Some(c);
        }
    }
    None
}

/// 优先 `uv run python app.py`（与 make dev / 启动器一致），否则回退 .venv/bin/python。
fn build_backend_command(root: &Path, port: u16) -> Result<Command, String> {
    let mut cmd = if let Some(uv) = find_uv().filter(|_| root.join("pyproject.toml").is_file()) {
        let mut c = Command::new(&uv);
        c.current_dir(root)
            .arg("run")
            .arg("python")
            .arg("app.py");
        c
    } else {
        let python = find_python(root)?;
        let mut c = Command::new(&python);
        c.current_dir(root).arg(root.join("app.py"));
        c
    };
    cmd.arg("--no-browser")
        .arg("--port")
        .arg(port.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    Ok(cmd)
}

fn apply_backend_env(cmd: &mut Command) {
    if std::env::var("PIANKE_NO_MIRROR").unwrap_or_default() != "1" {
        cmd.env("HF_ENDPOINT", "https://hf-mirror.com");
    }
}

fn venv_python_at(base: &Path) -> Option<PathBuf> {
    let candidates: Vec<PathBuf> = if cfg!(windows) {
        vec![
            base.join(".venv/Scripts/python.exe"),
            base.join("venv/Scripts/python.exe"),
        ]
    } else {
        vec![
            base.join(".venv/bin/python"),
            base.join("venv/bin/python"),
        ]
    };
    candidates.into_iter().find(|p| p.is_file())
}

fn debug_repo_root() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo = manifest.parent()?.parent()?;
        if repo.join("app.py").is_file() {
            return Some(repo.to_path_buf());
        }
    }
    None
}

fn find_python(root: &Path) -> Result<PathBuf, String> {
    let mut search_roots = vec![root.to_path_buf()];
    if let Ok(extra) = std::env::var("PIANKE_ROOT") {
        search_roots.push(PathBuf::from(extra));
    }
    if let Some(repo) = debug_repo_root() {
        search_roots.push(repo);
    }

    for base in search_roots {
        if let Some(py) = venv_python_at(&base) {
            return Ok(py);
        }
    }

    Ok(if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    })
}

fn pick_port(start: u16) -> Result<u16, String> {
    for offset in 0..PORT_TRIES {
        let port = start + offset;
        if port_is_free(port) {
            return Ok(port);
        }
    }
    Err(format!(
        "端口 {}-{} 均被占用，请关闭其他片刻实例或设置 PIC_SELECTER_PORT",
        start,
        start + PORT_TRIES - 1
    ))
}

fn port_is_free(port: u16) -> bool {
    TcpStream::connect(("127.0.0.1", port)).is_err()
}

fn wait_for_server(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}
