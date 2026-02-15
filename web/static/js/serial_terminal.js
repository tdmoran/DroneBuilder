/* FC Terminal — xterm.js init, SocketIO bridge, connection controls */

let term = null;
let fitAddon = null;
let socket = null;
let lastDiffAll = "";

// Initialize terminal
document.addEventListener("DOMContentLoaded", function () {
  term = new Terminal({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: "Menlo, Monaco, 'Courier New', monospace",
    theme: {
      background: "#1e1e1e",
      foreground: "#d4d4d4",
    },
  });

  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById("terminal"));
  fitAddon.fit();

  term.writeln("\x1b[36mDroneBuilder FC Terminal\x1b[0m");
  term.writeln("Connect a flight controller to begin.\r\n");

  // SocketIO connection
  socket = io("/serial", { transports: ["websocket", "polling"] });

  socket.on("serial_output", function (data) {
    term.write(data);
    lastDiffAll += data;
  });

  socket.on("connection_status", function (data) {
    updateConnectionUI(data.connected, data.port);
  });

  // Forward terminal input to serial
  term.onData(function (data) {
    if (socket && socket.connected) {
      socket.emit("serial_input", data);
    }
  });

  // Handle resize
  window.addEventListener("resize", function () {
    if (fitAddon) fitAddon.fit();
  });

  // Initial port scan
  refreshPorts();
  checkStatus();
});

function refreshPorts() {
  fetch("/serial/ports")
    .then((r) => r.json())
    .then(function (data) {
      const sel = document.getElementById("port-select");
      sel.innerHTML = "";

      if (data.ports.length === 0) {
        sel.innerHTML = '<option value="">No FC detected</option>';
        return;
      }

      data.ports.forEach(function (p) {
        const opt = document.createElement("option");
        opt.value = p.device;
        opt.textContent = p.device + " (" + p.description + ")";
        sel.appendChild(opt);
      });

      if (data.active_port) {
        sel.value = data.active_port;
      }
    })
    .catch(function () {
      document.getElementById("port-select").innerHTML =
        '<option value="">Scan failed</option>';
    });
}

function checkStatus() {
  fetch("/serial/status")
    .then((r) => r.json())
    .then(function (data) {
      updateConnectionUI(data.connected, data.port);
    });
}

function connectPort() {
  const port = document.getElementById("port-select").value;
  const baud = document.getElementById("baud-select").value;

  if (!port) {
    term.writeln("\r\n\x1b[31mNo port selected\x1b[0m");
    return;
  }

  term.writeln("\r\n\x1b[33mConnecting to " + port + "...\x1b[0m");

  fetch("/serial/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ port: port, baudrate: parseInt(baud) }),
  })
    .then((r) => r.json())
    .then(function (data) {
      if (data.connected) {
        term.writeln("\x1b[32mConnected!\x1b[0m\r\n");
        updateConnectionUI(true, port);
      } else {
        term.writeln("\x1b[31mFailed: " + (data.error || "Unknown error") + "\x1b[0m");
      }
    })
    .catch(function (err) {
      term.writeln("\x1b[31mConnection error: " + err + "\x1b[0m");
    });
}

function disconnectPort() {
  fetch("/serial/disconnect", { method: "POST" })
    .then((r) => r.json())
    .then(function () {
      term.writeln("\r\n\x1b[33mDisconnected\x1b[0m\r\n");
      updateConnectionUI(false, "");
    });
}

function updateConnectionUI(connected, port) {
  const btnConnect = document.getElementById("btn-connect");
  const btnDisconnect = document.getElementById("btn-disconnect");
  const btnReadConfig = document.getElementById("btn-read-config");
  const btnSaveConfig = document.getElementById("btn-save-config");
  const statusEl = document.getElementById("connection-status");

  btnConnect.disabled = connected;
  btnDisconnect.disabled = !connected;
  if (btnReadConfig) btnReadConfig.disabled = !connected;

  if (connected) {
    statusEl.innerHTML = '<span class="badge badge-active">Connected: ' + port + "</span>";
  } else {
    statusEl.innerHTML = '<span class="badge badge-retired">Disconnected</span>';
  }

  // Enable save if we have config data
  if (btnSaveConfig) {
    btnSaveConfig.disabled = !lastDiffAll;
  }
}

function readConfig() {
  term.writeln("\r\n\x1b[33mReading configuration...\x1b[0m");
  lastDiffAll = "";

  fetch("/serial/diff-all", { method: "POST" })
    .then((r) => r.json())
    .then(function (data) {
      if (data.error) {
        term.writeln("\x1b[31m" + data.error + "\x1b[0m");
        return;
      }

      lastDiffAll = data.raw_text;
      const resultEl = document.getElementById("config-result");
      resultEl.innerHTML =
        '<article><header><strong>' +
        data.firmware + " " + data.firmware_version +
        "</strong> &mdash; " + data.board_name +
        "</header><p>Features: " + data.features.join(", ") +
        "<br>Settings: " + data.settings_count +
        " | Serial ports: " + data.serial_ports_count +
        "</p></article>";

      term.writeln("\x1b[32mConfig read successfully!\x1b[0m\r\n");

      const btnSave = document.getElementById("btn-save-config");
      if (btnSave) btnSave.disabled = false;
    })
    .catch(function (err) {
      term.writeln("\x1b[31mRead failed: " + err + "\x1b[0m");
    });
}

function uploadDiffFile(input) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("diff_file", file);

  fetch("/serial/upload-diff", { method: "POST", body: formData })
    .then((r) => r.json())
    .then(function (data) {
      if (data.error) {
        if (term) term.writeln("\x1b[31m" + data.error + "\x1b[0m");
        return;
      }

      lastDiffAll = data.raw_text;
      const resultEl = document.getElementById("config-result");
      resultEl.innerHTML =
        '<article><header><strong>' +
        data.firmware + " " + data.firmware_version +
        "</strong> &mdash; " + data.board_name +
        "</header><p>Features: " + data.features.join(", ") +
        "<br>Settings: " + data.settings_count +
        " | Serial ports: " + data.serial_ports_count +
        "</p></article>";

      if (term) term.writeln("\r\n\x1b[32mDiff file loaded: " + file.name + "\x1b[0m\r\n");

      const btnSave = document.getElementById("btn-save-config");
      if (btnSave) btnSave.disabled = false;
    })
    .catch(function (err) {
      if (term) term.writeln("\x1b[31mUpload failed: " + err + "\x1b[0m");
    });

  input.value = "";
}

function saveConfig(slug) {
  if (!lastDiffAll) return;

  fetch("/serial/save-config/" + slug, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text: lastDiffAll }),
  })
    .then((r) => r.json())
    .then(function (data) {
      if (data.error) {
        if (term) term.writeln("\x1b[31m" + data.error + "\x1b[0m");
        return;
      }

      if (term) {
        term.writeln(
          "\r\n\x1b[32mConfig saved! " + data.firmware + " @ " + data.timestamp + "\x1b[0m\r\n"
        );
      }
    })
    .catch(function (err) {
      if (term) term.writeln("\x1b[31mSave failed: " + err + "\x1b[0m");
    });
}
