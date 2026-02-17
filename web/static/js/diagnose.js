/* DroneBuilder Diagnostic Page — wizard navigation, SocketIO progress,
   symptom autocomplete, and report export. */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

var currentStep = 1;
var selectedSymptoms = [];  // [{id: "cant_arm", label: "Will not arm"}, ...]
var diagSocket = null;
var scanResults = [];       // collected check results for export
var scanSummary = null;

// ---------------------------------------------------------------------------
// Step wizard navigation
// ---------------------------------------------------------------------------

function goToStep(step) {
  // Validate transitions
  if (step === 2 && !document.getElementById('drone-select').value) return;
  if (step === 3 && document.getElementById('config-loaded').value !== '1') return;

  // Hide all panels
  for (var i = 1; i <= 4; i++) {
    var panel = document.getElementById('step-' + i + '-panel');
    if (panel) {
      if (i === step) {
        panel.classList.remove('diag-panel-hidden');
        panel.classList.add('diag-panel-visible');
      } else {
        panel.classList.remove('diag-panel-visible');
        panel.classList.add('diag-panel-hidden');
      }
    }
  }

  // Update step indicator
  var steps = document.querySelectorAll('.diag-step');
  steps.forEach(function(el) {
    var s = parseInt(el.getAttribute('data-step'));
    el.classList.remove('active', 'completed');
    if (s === step) el.classList.add('active');
    else if (s < step) el.classList.add('completed');
  });

  currentStep = step;

  // Scroll to top of panel
  var activePanel = document.getElementById('step-' + step + '-panel');
  if (activePanel) {
    activePanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ---------------------------------------------------------------------------
// Drone selection
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function() {
  var sel = document.getElementById('drone-select');
  if (sel) {
    sel.addEventListener('change', function() {
      var btn = document.getElementById('btn-next-1');
      btn.disabled = !this.value;

      if (this.value) {
        fetch('/diagnose/drone-info/' + this.value)
          .then(function(r) { return r.text(); })
          .then(function(html) {
            document.getElementById('drone-preview').innerHTML = html;
          });
      } else {
        document.getElementById('drone-preview').innerHTML = '';
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Config load handling
// ---------------------------------------------------------------------------

function toggleUpload() {
  var area = document.getElementById('upload-area');
  area.style.display = area.style.display === 'none' ? 'block' : 'none';
}

// Handle file upload: read file into textarea
document.addEventListener('DOMContentLoaded', function() {
  var fileInput = document.getElementById('diff-file-input');
  if (fileInput) {
    fileInput.addEventListener('change', function(e) {
      var file = e.target.files[0];
      if (file) {
        var reader = new FileReader();
        reader.onload = function(ev) {
          document.getElementById('raw-text-input').value = ev.target.result;
        };
        reader.readAsText(file);
      }
    });
  }
});

// After config loads successfully (htmx response)
document.body.addEventListener('htmx:afterRequest', function(evt) {
  if (evt.detail.target && evt.detail.target.id === 'config-status') {
    try {
      var resp = JSON.parse(evt.detail.xhr.responseText);
      if (resp.raw_text) {
        document.getElementById('raw-text-input').value = resp.raw_text;
        document.getElementById('raw-text-hidden').value = resp.raw_text;
        document.getElementById('config-loaded').value = '1';
        document.getElementById('btn-next-2').disabled = false;

        // Show config status card
        var html = '<div class="diag-config-status">' +
          '<div class="diag-config-status-header">' +
          '<span class="diag-config-check">&#10003;</span>' +
          '<strong>FC Config Loaded</strong>' +
          '</div>' +
          '<div class="diag-config-status-details">' +
          '<div class="diag-config-detail"><span class="diag-config-detail-label">Firmware</span>' +
          resp.firmware + ' ' + resp.firmware_version + '</div>' +
          '<div class="diag-config-detail"><span class="diag-config-detail-label">Board</span>' +
          (resp.board_name || 'Unknown') + '</div>';

        if (resp.features_count !== undefined) {
          html += '<div class="diag-config-detail"><span class="diag-config-detail-label">Features</span>' +
            resp.features_count + ' active</div>';
        }
        if (resp.serial_ports_count !== undefined) {
          html += '<div class="diag-config-detail"><span class="diag-config-detail-label">Serial ports</span>' +
            resp.serial_ports_count + ' configured</div>';
        }

        html += '</div>';
        html += '<details class="diag-raw-config">' +
          '<summary>Show raw config dump</summary>' +
          '<pre>' + escapeHtml(resp.raw_text) + '</pre>' +
          '</details></div>';

        evt.detail.target.innerHTML = html;
      } else if (resp.error) {
        evt.detail.target.innerHTML =
          '<div class="diag-config-error">' +
          '<strong>Error:</strong> ' + escapeHtml(resp.error) + '</div>';
      }
    } catch(e) { /* not JSON — htmx partial */ }
  }
});

// ---------------------------------------------------------------------------
// Symptom selection
// ---------------------------------------------------------------------------

function selectSymptomSuggestion(btn) {
  var id = btn.getAttribute('data-symptom-id');
  var label = btn.getAttribute('data-symptom-label');
  addSymptom(id, label);
  document.getElementById('symptom-text-input').value = '';
  document.getElementById('symptom-suggestions').innerHTML = '';
}

function selectDropdownSymptom(sel) {
  if (!sel.value) return;
  var option = sel.options[sel.selectedIndex];
  addSymptom(sel.value, option.textContent.trim());
  sel.value = '';
}

function addSymptom(id, label) {
  // Prevent duplicates
  for (var i = 0; i < selectedSymptoms.length; i++) {
    if (selectedSymptoms[i].id === id) return;
  }

  selectedSymptoms.push({ id: id, label: label });
  renderSelectedSymptoms();
}

function removeSymptom(id) {
  selectedSymptoms = selectedSymptoms.filter(function(s) { return s.id !== id; });
  renderSelectedSymptoms();
}

function renderSelectedSymptoms() {
  var container = document.getElementById('selected-symptoms');

  // Remove old hidden inputs
  var oldInputs = document.querySelectorAll('.symptom-hidden-input');
  oldInputs.forEach(function(el) { el.remove(); });

  if (selectedSymptoms.length === 0) {
    container.innerHTML = '';
    return;
  }

  var html = '';
  selectedSymptoms.forEach(function(s) {
    html += '<span class="diag-symptom-tag">' +
      escapeHtml(s.label) +
      '<button type="button" class="diag-symptom-remove" onclick="removeSymptom(\'' + s.id + '\')">&times;</button>' +
      '</span>';

    // Add hidden input to form
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'symptoms';
    input.value = s.id;
    input.className = 'symptom-hidden-input';
    document.getElementById('diagnose-form').appendChild(input);
  });

  container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Diagnostic execution (SocketIO with htmx fallback)
// ---------------------------------------------------------------------------

function startDiagnostic() {
  goToStep(4);

  var droneFilename = document.getElementById('drone-select').value;
  var rawText = document.getElementById('raw-text-hidden').value;
  var symptoms = selectedSymptoms.map(function(s) { return s.id; });

  // Reset results
  scanResults = [];
  scanSummary = null;
  document.getElementById('diag-live-checks').innerHTML = '';
  document.getElementById('diag-summary').style.display = 'none';
  document.getElementById('diag-summary').innerHTML = '';
  document.getElementById('diag-result-actions').style.display = 'none';
  document.getElementById('discrepancy-results').innerHTML = '';
  document.getElementById('diagnostic-results').innerHTML = '';

  // Try SocketIO first
  if (typeof io !== 'undefined') {
    startSocketIOScan(droneFilename, rawText, symptoms);
  } else {
    // Fallback: use htmx form submission
    startHtmxFallbackScan(droneFilename, rawText, symptoms);
  }
}

function startSocketIOScan(droneFilename, rawText, symptoms) {
  // Show progress header
  document.getElementById('diag-progress-header').style.display = '';

  if (diagSocket) {
    diagSocket.disconnect();
  }

  diagSocket = io('/diagnose', { transports: ['websocket', 'polling'] });

  diagSocket.on('connect', function() {
    diagSocket.emit('start_scan', {
      drone_filename: droneFilename,
      raw_text: rawText,
      symptoms: symptoms,
    });
  });

  diagSocket.on('connect_error', function() {
    // Fallback to htmx if SocketIO fails
    startHtmxFallbackScan(droneFilename, rawText, symptoms);
  });

  diagSocket.on('scan_started', function(data) {
    document.getElementById('progress-build-name').textContent = data.build_name;
    document.getElementById('progress-fc-info').textContent = data.fc_info;
    setProgressBar(5);
  });

  diagSocket.on('section_started', function(data) {
    var checksEl = document.getElementById('diag-live-checks');
    var sectionEl = document.createElement('div');
    sectionEl.className = 'diag-section-group';
    sectionEl.id = 'section-' + data.section;
    sectionEl.innerHTML = '<div class="diag-section-header">' +
      '<span class="diag-section-spinner" aria-busy="true"></span> ' +
      escapeHtml(data.label) +
      '</div><div class="diag-section-checks"></div>';
    checksEl.appendChild(sectionEl);

    // Update progress bar
    if (data.section === 'discrepancy') setProgressBar(10);
    else if (data.section === 'compatibility') setProgressBar(40);
    else if (data.section === 'firmware') setProgressBar(70);
  });

  diagSocket.on('check_started', function(data) {
    var section = getCurrentSectionChecks();
    if (!section) return;

    var checkEl = document.createElement('div');
    checkEl.className = 'diag-check-row diag-check-running';
    checkEl.id = 'check-' + data.id;
    checkEl.innerHTML = '<span class="diag-check-icon diag-icon-spinner" aria-busy="true"></span>' +
      '<span class="diag-check-name">' + escapeHtml(data.name) + '</span>';
    section.appendChild(checkEl);
  });

  diagSocket.on('check_complete', function(data) {
    scanResults.push(data);

    var existingCheck = document.getElementById('check-' + data.id);
    var section = getCurrentSectionChecks();
    if (!section) return;

    var iconClass = data.passed ? 'diag-icon-pass' : 'diag-icon-' + data.severity;
    var iconChar = data.passed ? '&#10003;' : (
      data.severity === 'critical' ? '&#10007;' :
      data.severity === 'warning' ? '&#9888;' : '&#8505;'
    );

    var html = '<span class="diag-check-icon ' + iconClass + '">' + iconChar + '</span>' +
      '<span class="diag-check-name">' + escapeHtml(data.name) + '</span>' +
      '<span class="diag-check-badge severity-badge-' + data.severity + '">' +
      data.severity.toUpperCase() + '</span>';

    if (!data.passed && (data.message || data.fix)) {
      html += '<div class="diag-check-details">';
      if (data.message) html += '<p class="diag-check-message">' + escapeHtml(data.message) + '</p>';
      if (data.fleet_value && data.detected_value) {
        html += '<div class="diag-check-comparison">' +
          '<span class="diag-compare-item"><span class="diag-compare-label">Fleet:</span> ' + escapeHtml(data.fleet_value) + '</span>' +
          '<span class="diag-compare-item"><span class="diag-compare-label">FC:</span> ' + escapeHtml(data.detected_value) + '</span>' +
          '</div>';
      }
      if (data.fix) html += '<div class="diag-check-fix"><strong>Fix:</strong> ' + escapeHtml(data.fix) + '</div>';
      html += '<button type="button" class="diag-copy-btn outline" onclick="copyFinding(this)" data-text="' +
        escapeAttr(data.id + ': ' + (data.message || data.name) + (data.fix ? '\nFix: ' + data.fix : '')) +
        '">Copy</button>';
      html += '</div>';
    }

    if (existingCheck) {
      existingCheck.className = 'diag-check-row diag-check-done' + (data.passed ? '' : ' diag-check-failed');
      existingCheck.innerHTML = html;
    } else {
      var checkEl = document.createElement('div');
      checkEl.className = 'diag-check-row diag-check-done diag-check-enter' + (data.passed ? '' : ' diag-check-failed');
      checkEl.id = 'check-' + data.id;
      checkEl.innerHTML = html;
      section.appendChild(checkEl);
    }
  });

  diagSocket.on('checks_passed_batch', function(data) {
    var section = getCurrentSectionChecks();
    if (!section) return;

    var el = document.createElement('div');
    el.className = 'diag-check-row diag-check-done diag-check-batch diag-check-enter';
    el.innerHTML = '<span class="diag-check-icon diag-icon-pass">&#10003;</span>' +
      '<span class="diag-check-name">' + data.count + ' checks passed</span>';
    section.appendChild(el);
  });

  diagSocket.on('section_complete', function(data) {
    var sectionEl = document.getElementById('section-' + data.section);
    if (sectionEl) {
      var spinner = sectionEl.querySelector('.diag-section-spinner');
      if (spinner) {
        spinner.removeAttribute('aria-busy');
        if (data.issues === 0) {
          spinner.className = 'diag-section-icon diag-icon-pass';
          spinner.innerHTML = '&#10003;';
        } else {
          spinner.className = 'diag-section-icon diag-icon-warning';
          spinner.innerHTML = data.issues.toString();
        }
      }

      var header = sectionEl.querySelector('.diag-section-header');
      if (header) {
        header.innerHTML += ' <small>(' + data.total + ' checks, ' + data.issues + ' issues)</small>';
      }
    }
  });

  diagSocket.on('scan_complete', function(data) {
    scanSummary = data;
    setProgressBar(100);

    // Render summary card
    var summaryEl = document.getElementById('diag-summary');
    var healthClass = data.health === 'GOOD' ? 'diag-health-good' :
      data.health === 'ATTENTION' ? 'diag-health-attention' : 'diag-health-critical';

    var html = '<div class="diag-summary-card ' + healthClass + '">' +
      '<div class="diag-summary-health">' + data.health.replace('ATTENTION', 'NEEDS ATTENTION') + '</div>' +
      '<div class="diag-summary-title">' + escapeHtml(data.build_name) + '</div>' +
      '<div class="diag-summary-subtitle">' + escapeHtml(data.fc_info) + '</div>' +
      '<div class="diag-summary-counts">';

    if (data.critical > 0) {
      html += '<span class="diag-count-badge diag-count-critical">' + data.critical + ' Critical</span>';
    }
    if (data.warnings > 0) {
      html += '<span class="diag-count-badge diag-count-warning">' + data.warnings + ' Warning' + (data.warnings !== 1 ? 's' : '') + '</span>';
    }
    if (data.info > 0) {
      html += '<span class="diag-count-badge diag-count-info">' + data.info + ' Info</span>';
    }
    if (data.passed_checks > 0) {
      html += '<span class="diag-count-badge diag-count-pass">' + data.passed_checks + ' Passed</span>';
    }
    html += '</div>';

    // Config changes
    if (data.config_changes && data.config_changes.length > 0) {
      html += '<details class="diag-summary-changes">' +
        '<summary>' + data.config_changes.length + ' config change' +
        (data.config_changes.length !== 1 ? 's' : '') + ' since last backup</summary><ul>';
      data.config_changes.forEach(function(ch) {
        html += '<li>' + escapeHtml(ch) + '</li>';
      });
      html += '</ul></details>';
    }

    html += '</div>';
    summaryEl.innerHTML = html;
    summaryEl.style.display = '';

    // Show action buttons
    document.getElementById('diag-result-actions').style.display = '';

    // Hide progress bar
    document.getElementById('diag-progress-bar-wrap').style.display = 'none';

    diagSocket.disconnect();
  });

  diagSocket.on('scan_error', function(data) {
    document.getElementById('diag-live-checks').innerHTML +=
      '<div class="flash flash-error">' + escapeHtml(data.error) + '</div>';
    document.getElementById('diag-result-actions').style.display = '';
    if (diagSocket) diagSocket.disconnect();
  });
}

function startHtmxFallbackScan(droneFilename, rawText, symptoms) {
  // Build form data and submit via fetch to /diagnose/scan, then /diagnose/run
  var formData = new FormData();
  formData.append('drone_filename', droneFilename);
  formData.append('raw_text', rawText);
  symptoms.forEach(function(s) { formData.append('symptoms', s); });

  document.getElementById('diag-live-checks').innerHTML =
    '<div aria-busy="true" style="text-align:center;padding:2rem;">Running diagnostic scan...</div>';

  // First run scan (discrepancies)
  fetch('/diagnose/scan', { method: 'POST', body: formData })
    .then(function(r) { return r.text(); })
    .then(function(html) {
      document.getElementById('discrepancy-results').innerHTML = html;

      // Then run full diagnostic
      return fetch('/diagnose/run', { method: 'POST', body: formData });
    })
    .then(function(r) { return r.text(); })
    .then(function(html) {
      document.getElementById('diag-live-checks').innerHTML = '';
      document.getElementById('diagnostic-results').innerHTML = html;
      document.getElementById('diag-result-actions').style.display = '';
    })
    .catch(function(err) {
      document.getElementById('diag-live-checks').innerHTML =
        '<div class="flash flash-error">Scan failed: ' + err + '</div>';
      document.getElementById('diag-result-actions').style.display = '';
    });
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function setProgressBar(pct) {
  var bar = document.getElementById('diag-progress-bar');
  if (bar) bar.style.width = pct + '%';
}

function getCurrentSectionChecks() {
  var sections = document.querySelectorAll('.diag-section-checks');
  return sections.length > 0 ? sections[sections.length - 1] : null;
}

// ---------------------------------------------------------------------------
// Reset and export
// ---------------------------------------------------------------------------

function resetDiagnostic() {
  scanResults = [];
  scanSummary = null;
  selectedSymptoms = [];
  renderSelectedSymptoms();

  document.getElementById('config-loaded').value = '';
  document.getElementById('raw-text-hidden').value = '';
  document.getElementById('raw-text-input').value = '';
  document.getElementById('btn-next-2').disabled = true;
  document.getElementById('config-status').innerHTML = '';
  document.getElementById('symptom-text-input').value = '';
  document.getElementById('symptom-suggestions').innerHTML = '';
  document.getElementById('drone-preview').innerHTML = '';
  document.getElementById('diag-live-checks').innerHTML = '';
  document.getElementById('diag-summary').innerHTML = '';
  document.getElementById('diag-summary').style.display = 'none';
  document.getElementById('diag-result-actions').style.display = 'none';
  document.getElementById('discrepancy-results').innerHTML = '';
  document.getElementById('diagnostic-results').innerHTML = '';
  document.getElementById('diag-progress-header').style.display = 'none';
  document.getElementById('diag-progress-bar-wrap').style.display = '';

  goToStep(1);
}

function exportReport() {
  var lines = [];
  lines.push('DroneBuilder Diagnostic Report');
  lines.push('=============================');
  lines.push('Date: ' + new Date().toISOString());

  if (scanSummary) {
    lines.push('');
    lines.push('Drone: ' + scanSummary.build_name);
    lines.push('Firmware: ' + scanSummary.fc_info);
    lines.push('Health: ' + scanSummary.health);
    lines.push('');
    lines.push('Summary: ' + scanSummary.total_issues + ' issues (' +
      scanSummary.critical + ' critical, ' +
      scanSummary.warnings + ' warnings, ' +
      scanSummary.info + ' info), ' +
      scanSummary.passed_checks + ' passed');
  }

  if (scanResults.length > 0) {
    lines.push('');
    lines.push('Findings');
    lines.push('--------');

    var failures = scanResults.filter(function(r) { return !r.passed; });
    failures.forEach(function(r) {
      lines.push('');
      lines.push('[' + r.severity.toUpperCase() + '] ' + r.id + ': ' + r.name);
      if (r.message) lines.push('  ' + r.message);
      if (r.fleet_value && r.detected_value) {
        lines.push('  Fleet: ' + r.fleet_value + '  |  FC: ' + r.detected_value);
      }
      if (r.fix) lines.push('  Fix: ' + r.fix);
    });
  }

  if (scanSummary && scanSummary.config_changes && scanSummary.config_changes.length > 0) {
    lines.push('');
    lines.push('Config Changes');
    lines.push('--------------');
    scanSummary.config_changes.forEach(function(ch) {
      lines.push('  - ' + ch);
    });
  }

  var text = lines.join('\n');
  var blob = new Blob([text], { type: 'text/plain' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'diagnostic-report-' + new Date().toISOString().slice(0, 10) + '.txt';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function copyFinding(btn) {
  var text = btn.getAttribute('data-text');
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(function() {
      btn.textContent = 'Copied';
      setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
    });
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function escapeAttr(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '&#10;');
}
