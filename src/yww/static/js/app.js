// YWW - Main Application JavaScript

const App = {
  jobs: new Map(),
  activeJobId: null,
  advancedOpen: false,
  timestampMode: false,
  outputPath: '',
  history: [],
  rtfStats: {},

  // DOM Elements
  elements: {},

  init() {
    this.cacheElements();
    this.bindEvents();
    this.loadModelStats();
    this.loadHistory();
    this.loadJobs();
    this.setupKeyboardShortcuts();
    this.setupDragAndDrop();
    this.outputPath = this.elements.outputPath?.dataset.path || '';
    this.loadSystemInfo();
    console.log('YWW initialized');
  },

  async loadSystemInfo() {
    try {
      const res = await fetch('/api/system');
      const info = await res.json();
      this.systemInfo = info;
      console.log('System:', info.device, info.mps_available ? '(MPS)' : '(CPU)');
    } catch (err) {
      console.warn('Could not load system info:', err);
    }
  },

  cacheElements() {
    this.elements = {
      urlInput: document.getElementById('url-input'),
      transcribeBtn: document.getElementById('transcribe-btn'),
      modelSelect: document.getElementById('model-select'),
      langSelect: document.getElementById('lang-select'),
      outputPath: document.getElementById('output-path'),
      folderPicker: document.getElementById('folder-picker'),
      advancedToggle: document.getElementById('advanced-toggle'),
      advancedPanel: document.getElementById('advanced-panel'),
      timestampToggle: document.getElementById('timestamp-toggle'),
      timestampPanel: document.getElementById('timestamp-panel'),
      startTime: document.getElementById('start-time'),
      endTime: document.getElementById('end-time'),
      jobsList: document.getElementById('jobs-list'),
      heroView: document.getElementById('hero-view'),
      jobDetailView: document.getElementById('job-detail-view'),
      dropOverlay: document.getElementById('drop-overlay'),
      contextMenu: document.getElementById('context-menu'),
      toast: document.getElementById('toast'),
    };
  },

  bindEvents() {
    this.elements.transcribeBtn?.addEventListener('click', () => this.submitJob());
    this.elements.urlInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.submitJob();
    });
    this.elements.advancedToggle?.addEventListener('click', () => this.toggleAdvanced());
    this.elements.timestampToggle?.addEventListener('click', () => this.toggleTimestamp());
    document.addEventListener('click', () => this.closeContextMenu());
  },

  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'l') {
        e.preventDefault();
        this.elements.urlInput?.focus();
        this.elements.urlInput?.select();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        this.showHeroView();
        this.elements.urlInput.value = '';
        this.elements.urlInput?.focus();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'o' && !e.shiftKey) {
        e.preventDefault();
        this.revealOutputFolder();
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'O') {
        e.preventDefault();
        this.chooseFolder();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 't') {
        e.preventDefault();
        this.toggleTimestamp();
      }
      if (e.key === 'Escape') {
        this.closeContextMenu();
        this.closeFolderModal();
        if (this.advancedOpen) this.toggleAdvanced();
        if (this.timestampMode) this.toggleTimestamp();
      }
    });
  },

  setupDragAndDrop() {
    const overlay = this.elements.dropOverlay;
    if (!overlay) return;

    let dragCounter = 0;

    document.addEventListener('dragenter', (e) => {
      e.preventDefault();
      dragCounter++;
      overlay.classList.add('active');
    });

    document.addEventListener('dragleave', (e) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter === 0) {
        overlay.classList.remove('active');
      }
    });

    document.addEventListener('dragover', (e) => {
      e.preventDefault();
    });

    document.addEventListener('drop', (e) => {
      e.preventDefault();
      dragCounter = 0;
      overlay.classList.remove('active');

      const text = e.dataTransfer.getData('text/plain');
      if (text && (text.includes('youtube.com') || text.includes('youtu.be'))) {
        this.elements.urlInput.value = text;
        this.elements.urlInput?.focus();
        this.showNotification('URL pasted! Press Enter or click Transcribe', 'success');
      }
    });
  },

  toggleAdvanced() {
    this.advancedOpen = !this.advancedOpen;
    this.elements.advancedPanel?.classList.toggle('open', this.advancedOpen);
    const btn = this.elements.advancedToggle;
    if (btn) {
      btn.innerHTML = `<span class="chevron" style="transform: rotate(${this.advancedOpen ? 180 : 0}deg)">&#9662;</span> Advanced Options`;
    }
  },

  toggleTimestamp() {
    this.timestampMode = !this.timestampMode;
    this.elements.timestampPanel?.classList.toggle('open', this.timestampMode);
    const btn = this.elements.timestampToggle;
    if (btn) {
      btn.classList.toggle('active', this.timestampMode);
    }
    if (this.elements.transcribeBtn) {
      this.elements.transcribeBtn.textContent = this.timestampMode ? 'Transcribe Range' : 'Transcribe';
    }
  },

  async submitJob() {
    const url = this.elements.urlInput?.value.trim();
    if (!url) {
      this.elements.urlInput?.focus();
      this.showNotification('Please enter a YouTube URL', 'error');
      return;
    }

    if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
      this.showNotification('Please enter a valid YouTube URL', 'error');
      return;
    }

    const btn = this.elements.transcribeBtn;
    btn.disabled = true;
    btn.textContent = 'Starting...';

    const startTime = this.timestampMode ? this.elements.startTime?.value.trim() : null;
    const endTime = this.timestampMode ? this.elements.endTime?.value.trim() : null;

    if (this.timestampMode && startTime) {
      if (!this.isValidTimestamp(startTime)) {
        this.showNotification('Invalid start time format. Use HH:MM:SS or MM:SS', 'error');
        btn.disabled = false;
        btn.textContent = 'Transcribe Range';
        return;
      }
      if (endTime && !this.isValidTimestamp(endTime)) {
        this.showNotification('Invalid end time format. Use HH:MM:SS or MM:SS', 'error');
        btn.disabled = false;
        btn.textContent = 'Transcribe Range';
        return;
      }
    }

    try {
      const body = {
        url,
        out: this.outputPath || this.elements.outputPath?.dataset.path || '',
        model: this.getModelValue(),
        lang: this.elements.langSelect?.value || 'auto',
        force: document.getElementById('force-checkbox')?.checked || false,
        start_time: startTime || null,
        end_time: endTime || null,
        format: document.getElementById('format-select')?.value || 'srt',
        keep_audio: document.getElementById('keep-audio-checkbox')?.checked || false,
      };

      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (data.error) {
        throw new Error(data.detail || data.error);
      }

      if (data.job_id) {
        this.addJob(data.job_id, url, { startTime, endTime, model: body.model, lang: body.lang, format: body.format });
        this.elements.urlInput.value = '';
        if (this.timestampMode) {
          this.elements.startTime.value = '';
          this.elements.endTime.value = '';
        }
        this.pollJob(data.job_id);
        this.showNotification('Job started!', 'success');
      }
    } catch (err) {
      this.showNotification('Failed to start: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = this.timestampMode ? 'Transcribe Range' : 'Transcribe';
    }
  },

  isValidTimestamp(ts) {
    return /^(\d{1,2}:)?(\d{1,2}:)?\d{1,2}(\.\d+)?$/.test(ts) || /^\d+(\.\d+)?$/.test(ts);
  },

  getModelValue() {
    const advModel = document.getElementById('model-advanced')?.value;
    if (advModel && this.advancedOpen) return advModel;

    const select = this.elements.modelSelect;
    if (!select) return 'base';
    const val = select.value;
    const map = { 'Fast': 'tiny', 'Balanced': 'base', 'Best': 'small' };
    return map[val] || val;
  },

  addJob(jobId, url, options = {}) {
    const job = {
      id: jobId,
      url,
      title: this.extractTitle(url),
      status: 'queued',
      progress: 0,
      events: [],
      result: null,
      error: null,
      startTime: options.startTime,
      endTime: options.endTime,
      startedAt: Date.now(),
      downloadStarted: null,
      downloadBytes: 0,
      totalBytes: 0,
      transcribeStarted: null,
      model: options.model || 'tiny',
      lang: options.lang || 'auto',
      format: options.format || 'txt',
      out: this.outputPath || this.elements.outputPath?.dataset.path || '',
    };
    this.jobs.set(jobId, job);
    this.renderJobsList();
    this.selectJob(jobId);
  },

  extractTitle(url) {
    try {
      const u = new URL(url);
      return u.searchParams.get('v') || url.split('/').pop() || 'Video';
    } catch {
      return 'Video';
    }
  },

  renderJobsList() {
    const list = this.elements.jobsList;
    if (!list) return;

    if (this.jobs.size === 0) {
      list.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">&#128196;</div>
          <div class="empty-state-title">No jobs yet</div>
          <div>Paste a YouTube URL to get started</div>
        </div>
      `;
      return;
    }

    const jobsArray = Array.from(this.jobs.values()).reverse();
    list.innerHTML = jobsArray.map(job => `
      <div class="job-item ${job.id === this.activeJobId ? 'active' : ''}"
           data-job-id="${job.id}"
           onclick="App.selectJob('${job.id}')"
           oncontextmenu="App.showContextMenu(event, '${job.id}')">
        <div class="job-item-title">${this.escapeHtml(job.title)}</div>
        <div class="job-item-meta">
          <span class="status-badge status-${job.status}">${this.formatStatus(job.status)}</span>
          ${job.startTime ? `<span class="time-badge">${job.startTime}${job.endTime ? ' - ' + job.endTime : ''}</span>` : ''}
        </div>
        ${job.status === 'running' ? `<div class="job-item-progress"><div class="job-item-progress-fill" style="width: ${this.calculateProgress(job)}%"></div></div>` : ''}
      </div>
    `).join('');
  },

  formatStatus(status) {
    const map = {
      'queued': 'Queued',
      'pending': 'Queued',
      'running': 'Running',
      'completed': 'Done',
      'done': 'Done',
      'error': 'Failed',
    };
    return map[status] || status;
  },

  selectJob(jobId) {
    this.activeJobId = jobId;
    this.renderJobsList();
    this.renderJobDetail(jobId);
  },

  renderJobDetail(jobId) {
    const job = this.jobs.get(jobId);
    if (!job) return;

    this.elements.heroView?.classList.add('hidden');
    this.elements.jobDetailView?.classList.remove('hidden');

    const detail = this.elements.jobDetailView;
    if (!detail) return;

    const pipelineSteps = this.getPipelineSteps(job);
    const progressPercent = this.calculateProgress(job);
    const progressInfo = this.getProgressInfo(job);

    detail.innerHTML = `
      <div class="job-header">
        <div class="job-header-top">
          <button class="back-btn" onclick="App.showHeroView()">&#8592; New</button>
        </div>
        <h2 class="job-title">${this.escapeHtml(job.title)}</h2>
        <div class="job-url">${this.escapeHtml(job.url)}</div>
        ${job.startTime ? `
          <div class="job-time-range">
            <span class="time-badge large">${job.startTime}${job.endTime ? ' - ' + job.endTime : ' onwards'}</span>
          </div>
        ` : ''}
      </div>

      <!-- Pipeline Steps -->
      <div class="pipeline">
        ${pipelineSteps.map((step, i) => `
          <div class="pipeline-step ${step.state}">
            <div class="step-icon">
              ${step.state === 'done' ? '&#10003;' : step.state === 'active' ? '<span class="spinner"></span>' : i + 1}
            </div>
            <div class="step-label">${step.label}</div>
          </div>
        `).join('')}
      </div>

      <!-- Progress Section -->
      ${job.status === 'running' || job.status === 'pending' || job.status === 'queued' ? `
        <div class="progress-section">
          <div class="progress-header">
            <span class="progress-status">
              <span class="spinner ${progressInfo.phase}"></span>
              ${progressInfo.status}
            </span>
            <span class="progress-eta">${progressInfo.eta}</span>
          </div>
          <div class="progress-bar-container">
            <div class="progress-bar-track">
              <div class="progress-bar-fill ${progressInfo.phase}" style="width: ${progressPercent}%"></div>
            </div>
          </div>
          <div class="progress-detail">
            <span>${progressInfo.detail}</span>
            <span class="progress-percent">${progressPercent}%</span>
          </div>
          ${progressInfo.audioDuration ? `
            <div class="progress-info">
              <span>Audio: ${progressInfo.audioDuration}</span>
              ${progressInfo.estimatedTime ? `<span>Est. time: ${progressInfo.estimatedTime}</span>` : ''}
            </div>
          ` : ''}
        </div>
      ` : ''}

      ${job.status === 'completed' || job.status === 'done' ? this.renderOutputCard(job) : ''}
      ${job.status === 'error' ? this.renderErrorCard(job) : ''}
    `;
  },

  getPipelineSteps(job) {
    const steps = [
      { label: 'Fetch', state: 'pending' },
      { label: 'Download', state: 'pending' },
      { label: 'Transcribe', state: 'pending' },
      { label: 'Export', state: 'pending' },
    ];

    const events = job.events || [];
    const hasStart = events.some(e => e.event === 'start');
    const hasProgress = events.some(e => e.event === 'download_progress');
    const hasDownloaded = events.some(e => e.event === 'downloaded' || e.event === 'download_complete');
    const hasTranscribed = events.some(e => e.event === 'transcribe_complete' || e.event === 'transcribed' || e.event === 'skip_transcription');
    const hasIndexed = events.some(e => e.event === 'indexed');

    if (hasStart) steps[0].state = 'done';
    if (hasProgress && !hasDownloaded) steps[1].state = 'active';
    if (hasDownloaded) {
      steps[1].state = 'done';
      steps[2].state = 'active';
    }
    if (hasTranscribed) {
      steps[2].state = 'done';
      steps[3].state = 'active';
    }
    if (hasIndexed) steps[3].state = 'done';

    if (job.status === 'completed' || job.status === 'done') {
      steps.forEach(s => s.state = 'done');
    }

    return steps;
  },

  calculateProgress(job) {
    const events = job.events || [];
    const hasIndexed = events.some(e => e.event === 'indexed');
    const transcribeDone = events.some(e => e.event === 'transcribe_complete' || e.event === 'transcribed' || e.event === 'skip_transcription');
    const downloadDone = events.some(e => e.event === 'download_complete' || e.event === 'downloaded');
    const lastDownload = [...events].reverse().find(e => e.event === 'download_progress');

    if (hasIndexed || job.status === 'completed' || job.status === 'done') return 100;
    if (transcribeDone) return 95;

    if (downloadDone) {
      const totalTime = this.estimateTranscribeTotal(job);
      if (job.transcribeStarted && totalTime) {
        const elapsed = (Date.now() - job.transcribeStarted) / 1000;
        const pct = Math.min(1, elapsed / totalTime);
        return Math.min(95, Math.round(50 + pct * 45));
      }
      return 55;
    }

    if (lastDownload && lastDownload.total_bytes) {
      const pct = lastDownload.downloaded_bytes / lastDownload.total_bytes;
      return Math.min(50, Math.max(5, Math.round(pct * 50)));
    }

    return 5;
  },

  getProgressInfo(job) {
    const events = job.events || [];
    const lastProgress = [...events].reverse().find(e => e.event === 'download_progress');
    const hasDownloaded = events.some(e => e.event === 'download_complete' || e.event === 'downloaded');
    const hasTranscribed = events.some(e => e.event === 'transcribe_complete' || e.event === 'transcribed' || e.event === 'skip_transcription');

    // Look for transcription events
    const transcribeInit = events.find(e => e.event === 'transcribe_init');
    const audioLoaded = events.find(e => e.event === 'transcribe_audio_loaded');
    const transcribeComplete = events.find(e => e.event === 'transcribe_complete');

    let status = 'Starting...';
    let detail = '';
    let eta = '';
    let phase = 'download';
    let audioDuration = null;
    let estimatedTime = null;

    if (hasTranscribed || transcribeComplete) {
      status = 'Finalizing...';
      detail = 'Saving transcript';
      eta = 'Almost done';
      phase = 'finalize';
    } else if (hasDownloaded) {
      status = 'Transcribing...';
      phase = 'transcribe';
      const durationSeconds = audioLoaded?.duration_seconds;
      const rtf = audioLoaded?.estimated_time_seconds && durationSeconds
        ? durationSeconds / audioLoaded.estimated_time_seconds
        : this.medianRtf(job.model || 'tiny');
      const totalTime = durationSeconds && rtf ? durationSeconds / rtf : null;
      const transcribeStart = job.transcribeStarted || Date.now();
      const elapsed = (Date.now() - transcribeStart) / 1000;
      const remaining = totalTime ? Math.max(totalTime - elapsed, 0) : null;

      if (audioLoaded) {
        audioDuration = audioLoaded.duration_formatted;
        estimatedTime = totalTime ? this.formatDuration(totalTime) : audioLoaded.estimated_time_formatted;
        detail = `Audio: ${audioDuration}`;
      } else if (transcribeInit) {
        detail = `Model: ${transcribeInit.model || 'base'}, Device: ${transcribeInit.device || 'cpu'}`;
      } else {
        detail = 'Processing audio...';
      }

      if (remaining !== null) {
        eta = `~${this.formatDuration(remaining)}`;
      } else {
        eta = `${Math.round(elapsed)}s elapsed`;
      }
    } else if (lastProgress) {
      status = 'Downloading...';
      phase = 'download';

      const downloaded = lastProgress.downloaded_bytes || 0;
      const total = lastProgress.total_bytes || 0;
      const speed = lastProgress.speed || 0;

      detail = `${this.formatBytes(downloaded)}`;
      if (total) {
        detail += ` / ${this.formatBytes(total)}`;
      }
      if (speed) {
        detail += ` • ${this.formatBytes(speed)}/s`;
      }

      // Calculate ETA
      if (total && speed && speed > 0) {
        const remaining = (total - downloaded) / speed;
        eta = `~${this.formatDuration(remaining)}`;
      } else if (lastProgress.eta) {
        eta = `~${lastProgress.eta}s remaining`;
      } else {
        eta = 'Calculating...';
      }
    } else {
      status = 'Connecting...';
      detail = 'Fetching video info';
      eta = '';
    }

    return { status, detail, eta, phase, audioDuration, estimatedTime };
  },

  renderOutputCard(job) {
    const result = job.result || {};
    const files = [];

    if (result.transcript) {
      files.push({
        name: result.transcript.split('/').pop(),
        path: result.transcript,
        icon: '&#128196;',
        type: 'transcript',
      });
    }
    if (result.file) {
      files.push({
        name: result.file.split('/').pop(),
        path: result.file,
        icon: '&#127925;',
        type: 'audio',
      });
    }

    if (files.length === 0) return '';

    const folderPath = result.transcript ? result.transcript.split('/').slice(0, -1).join('/') : '';
    const duration = ((Date.now() - job.startedAt) / 1000).toFixed(1);

    return `
      <div class="completion-banner">
        <span class="completion-icon">&#10003;</span>
        <span class="completion-text">Completed in ${duration}s</span>
      </div>

      <div class="output-card">
        <div class="output-card-title">Outputs</div>
        <div class="output-files">
          ${files.map(f => `
            <div class="output-file">
              <div class="output-file-info">
                <div class="output-file-icon">${f.icon}</div>
                <div>
                  <div class="output-file-name">${this.escapeHtml(f.name)}</div>
                  <div class="output-file-size">${f.type}</div>
                </div>
              </div>
              <div class="output-file-actions">
                <button class="icon-btn" data-tooltip="Copy path" onclick="App.copyToClipboard('${this.escapeJs(f.path)}')">
                  &#128203;
                </button>
                <button class="icon-btn" data-tooltip="Reveal in Finder" onclick="App.revealFile('${this.escapeJs(f.path)}')">
                  &#128193;
                </button>
                ${f.type === 'transcript' ? `
                  <button class="btn-primary" onclick="App.openFile('${this.escapeJs(f.path)}')">
                    Open
                  </button>
                ` : ''}
              </div>
            </div>
          `).join('')}
        </div>
        <div class="output-actions">
          <button class="btn-secondary" onclick="App.revealFile('${this.escapeJs(folderPath)}')">
            &#128193; Open Folder
          </button>
          <button class="btn-secondary" onclick="App.showAIPanel('${job.id}')">
            &#10024; AI Enhance
          </button>
        </div>
      </div>

      <div class="ai-panel" id="ai-panel-${job.id}" style="display: none;">
        <div class="output-card-title">AI Enhancement</div>
        <div class="ai-options">
          <button class="ai-option" onclick="App.runAI('${job.id}', 'summary')">
            <span class="ai-icon">&#128221;</span>
            <span class="ai-label">Summary</span>
            <span class="ai-desc">Concise overview of key points</span>
          </button>
          <button class="ai-option" onclick="App.runAI('${job.id}', 'highlights')">
            <span class="ai-icon">&#11088;</span>
            <span class="ai-label">Highlights</span>
            <span class="ai-desc">Important moments & quotes</span>
          </button>
          <button class="ai-option" onclick="App.runAI('${job.id}', 'chapters')">
            <span class="ai-icon">&#128218;</span>
            <span class="ai-label">Chapters</span>
            <span class="ai-desc">Structured sections with timestamps</span>
          </button>
          <button class="ai-option" onclick="App.runAI('${job.id}', 'action_items')">
            <span class="ai-icon">&#9989;</span>
            <span class="ai-label">Action Items</span>
            <span class="ai-desc">Tasks & takeaways to act on</span>
          </button>
          <button class="ai-option" onclick="App.runAI('${job.id}', 'questions')">
            <span class="ai-icon">&#10067;</span>
            <span class="ai-label">Q&A</span>
            <span class="ai-desc">Key questions answered in content</span>
          </button>
          <button class="ai-option" onclick="App.runAI('${job.id}', 'tweet_thread')">
            <span class="ai-icon">&#128038;</span>
            <span class="ai-label">Tweet Thread</span>
            <span class="ai-desc">Social-ready summary thread</span>
          </button>
        </div>
        <div class="ai-status" id="ai-status-${job.id}"></div>
      </div>
    `;
  },

  renderErrorCard(job) {
    const errorMsg = job.error || 'An unknown error occurred';
    const errorDetail = job.events?.find(e => e.event === 'error_detail')?.trace || '';

    return `
      <div class="error-card">
        <div class="error-title">Transcription Failed</div>
        <div class="error-message">${this.escapeHtml(errorMsg)}</div>
        <div class="error-actions">
          <button class="btn-primary" onclick="App.retryJob('${job.id}')">Retry</button>
          <button class="btn-secondary" onclick="App.toggleErrorDetails('${job.id}')">Show Details</button>
          <button class="btn-secondary" onclick="App.copyToClipboard(\`${this.escapeHtml(errorMsg)}\n\n${this.escapeHtml(errorDetail)}\`)">Copy Diagnostics</button>
        </div>
        <pre class="error-details" id="error-details-${job.id}">${this.escapeHtml(errorDetail)}</pre>
      </div>
    `;
  },

  toggleErrorDetails(jobId) {
    const el = document.getElementById(`error-details-${jobId}`);
    el?.classList.toggle('open');
  },

  showAIPanel(jobId) {
    const panel = document.getElementById(`ai-panel-${jobId}`);
    if (panel) {
      panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
  },

  async runAI(jobId, type) {
    const job = this.jobs.get(jobId);
    if (!job?.result?.transcript) {
      this.showNotification('No transcript available', 'error');
      return;
    }

    const statusEl = document.getElementById(`ai-status-${jobId}`);
    if (statusEl) {
      statusEl.innerHTML = `<div class="ai-loading"><span class="spinner"></span> Processing ${type}...</div>`;
    }

    try {
      const res = await fetch('/api/enhance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript: job.result.transcript,
          type: type,
        }),
      });

      const data = await res.json();

      if (data.error) {
        throw new Error(data.error);
      }

      if (statusEl) {
        statusEl.innerHTML = `
          <div class="ai-success">
            &#10003; ${type} generated!
            <button class="link-btn" onclick="App.openFile('${this.escapeJs(data.file)}')">Open</button>
            <button class="link-btn" onclick="App.revealFile('${this.escapeJs(data.file)}')">Reveal</button>
          </div>
        `;
      }
      this.showNotification(`${type} generated successfully!`, 'success');
    } catch (err) {
      if (statusEl) {
        statusEl.innerHTML = `<div class="ai-error">Error: ${this.escapeHtml(err.message)}</div>`;
      }
      this.showNotification('AI enhancement failed: ' + err.message, 'error');
    }
  },

  async pollJob(jobId) {
    const job = this.jobs.get(jobId);
    if (!job) return;

    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const data = await res.json();

      const prevEvents = job.events || [];
      const wasDownloaded = prevEvents.some(e => e.event === 'downloaded' || e.event === 'download_complete');
      const isNowDownloaded = data.events?.some(e => e.event === 'downloaded' || e.event === 'download_complete');

      job.status = data.status === 'completed' ? 'done' : data.status;
      job.events = data.events || [];
      job.result = data.result;
      job.error = data.error;

      if (data.result?.meta?.title) {
        job.title = data.result.meta.title;
      }
      if (data.result?.meta?.language) {
        job.lang = data.result.meta.language;
      }

      // Track when transcription starts with event timestamp
      if (!job.transcribeStarted) {
        const startEvt = job.events.find(e => e.event === 'transcribe_start');
        if (startEvt?.ts) {
          job.transcribeStarted = startEvt.ts * 1000;
        } else if (isNowDownloaded && !wasDownloaded) {
          job.transcribeStarted = Date.now();
        }
      }

      // Capture RTF for future estimations
      const tc = job.events.find(e => e.event === 'transcribe_complete' && e.realtime_factor);
      if (tc?.realtime_factor && !job.rtfRecorded) {
        this.recordRtf(job.model || 'tiny', tc.realtime_factor);
        job.rtfRecorded = true;
      }

      this.renderJobsList();
      if (this.activeJobId === jobId) {
        this.renderJobDetail(jobId);
      }

      if (data.status !== 'completed' && data.status !== 'error') {
        setTimeout(() => this.pollJob(jobId), 500); // Poll faster for smoother progress
      } else {
        this.recordHistory(job);
        if (data.status === 'completed') {
          this.showNotification('Transcription complete!', 'success');
        }
      }
    } catch (err) {
      console.error('Poll error:', err);
      setTimeout(() => this.pollJob(jobId), 2000);
    }
  },

  async retryJob(jobId) {
    const job = this.jobs.get(jobId);
    if (!job) return;

    this.elements.urlInput.value = job.url;
    if (job.startTime) {
      this.timestampMode = true;
      this.elements.timestampPanel?.classList.add('open');
      if (this.elements.startTime) this.elements.startTime.value = job.startTime;
      if (this.elements.endTime) this.elements.endTime.value = job.endTime || '';
    }
    this.jobs.delete(jobId);
    this.renderJobsList();
    this.showHeroView();
  },

  showHeroView() {
    this.activeJobId = null;
    this.elements.heroView?.classList.remove('hidden');
    this.elements.jobDetailView?.classList.add('hidden');
    this.renderJobsList();
  },

  showContextMenu(e, jobId) {
    e.preventDefault();
    e.stopPropagation();

    const menu = this.elements.contextMenu;
    if (!menu) return;

    const job = this.jobs.get(jobId);
    if (!job) return;

    menu.innerHTML = `
      ${job.result?.transcript ? `
        <div class="context-menu-item" onclick="App.openFile('${this.escapeJs(job.result.transcript)}')">Open Transcript</div>
        <div class="context-menu-item" onclick="App.copyToClipboard('${this.escapeJs(job.result.transcript)}')">Copy Path</div>
        <div class="context-menu-item" onclick="App.revealFile('${this.escapeJs(job.result.transcript)}')">Reveal in Finder</div>
        <div class="context-menu-divider"></div>
      ` : ''}
      ${job.status === 'error' ? `
        <div class="context-menu-item" onclick="App.retryJob('${jobId}')">Retry</div>
      ` : ''}
      <div class="context-menu-item" onclick="App.copyToClipboard('${this.escapeJs(job.url)}')">Copy URL</div>
      <div class="context-menu-divider"></div>
      <div class="context-menu-item danger" onclick="App.deleteJob('${jobId}')">Remove from List</div>
    `;

    const x = Math.min(e.clientX, window.innerWidth - 200);
    const y = Math.min(e.clientY, window.innerHeight - 200);
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.classList.add('open');
  },

  closeContextMenu() {
    this.elements.contextMenu?.classList.remove('open');
  },

  deleteJob(jobId) {
    this.jobs.delete(jobId);
    if (this.activeJobId === jobId) {
      this.showHeroView();
    }
    this.renderJobsList();
    this.closeContextMenu();
  },

  async copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      this.showNotification('Copied to clipboard', 'success');
    } catch (err) {
      console.error('Copy failed:', err);
      this.showNotification('Copy failed', 'error');
    }
  },

  async openFile(path) {
    try {
      await fetch('/api/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
    } catch (err) {
      window.open(`file://${path}`, '_blank');
    }
  },

  async revealFile(path) {
    try {
      const res = await fetch('/api/reveal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) {
        throw new Error('Reveal failed');
      }
    } catch (err) {
      this.showNotification('Could not reveal file: ' + err.message, 'error');
    }
  },

  revealOutputFolder() {
    const path = this.outputPath || this.elements.outputPath?.dataset.path;
    if (path) {
      this.revealFile(path);
    } else {
      this.showNotification('No output folder set', 'error');
    }
  },

  // Native folder picker using webkitdirectory
  chooseFolder() {
    const picker = this.elements.folderPicker;
    if (picker) {
      // Try the native picker first
      picker.click();

      // If user doesn't select anything within 100ms, show the manual dialog
      // This handles cases where the native picker might not work
      setTimeout(() => {
        // Check if we got any selection; if not, show manual dialog
        // The native picker is async, so we rely on onFolderSelected callback
      }, 100);
    } else {
      // Fallback: show manual dialog
      this.showFolderDialog('Transcripts');
    }
  },

  onFolderSelected(event) {
    const files = event.target.files;
    if (files && files.length > 0) {
      // Get the folder path from the first file's webkitRelativePath
      const firstFile = files[0];
      const relativePath = firstFile.webkitRelativePath;
      const folderName = relativePath.split('/')[0];

      // Unfortunately, we can't get the full absolute path from the browser
      // So we'll construct it based on common patterns or ask the user
      // For now, we'll use a smarter approach - get the folder name and
      // let the user confirm/edit via a nicer dialog

      this.showFolderDialog(folderName);
    }
    // Reset the input so the same folder can be selected again
    event.target.value = '';
  },

  showFolderDialog(selectedFolderName) {
    const modal = document.getElementById('folder-modal');
    const input = document.getElementById('folder-path-input');
    const suggestions = document.getElementById('folder-suggestions');

    if (!modal) return;

    // Set current path in input
    if (input) {
      input.value = this.outputPath || '';
      input.placeholder = `/Users/yourname/${selectedFolderName || 'Transcripts'}`;
    }

    // Populate quick suggestions
    if (suggestions) {
      const paths = [
        { label: 'Documents/Transcripts', path: '~/Documents/Transcripts' },
        { label: 'Downloads', path: '~/Downloads' },
        { label: 'Desktop', path: '~/Desktop' },
        { label: selectedFolderName, path: `~/${selectedFolderName}` },
      ].filter((p, i, arr) => arr.findIndex(x => x.path === p.path) === i); // Remove duplicates

      suggestions.innerHTML = paths.map(p => `
        <button class="suggestion-btn" onclick="App.setFolderPath('${p.path}')">${p.label}</button>
      `).join('');
    }

    // Show modal with animation
    modal.classList.add('show');

    // Focus the input
    setTimeout(() => input?.focus(), 100);
  },

  setFolderPath(path) {
    const input = document.getElementById('folder-path-input');
    if (input) {
      input.value = path;
      input.focus();
    }
  },

  closeFolderModal() {
    const modal = document.getElementById('folder-modal');
    if (modal) {
      modal.classList.remove('show');
    }
  },

  async confirmFolder() {
    const input = document.getElementById('folder-path-input');
    const path = input?.value.trim();

    if (!path) {
      this.showNotification('Please enter a folder path', 'error');
      return;
    }

    try {
      const res = await fetch('/api/validate-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const data = await res.json();

      if (data.valid) {
        this.outputPath = data.path;
        if (this.elements.outputPath) {
          this.elements.outputPath.dataset.path = data.path;
          this.elements.outputPath.textContent = this.truncatePath(data.path);
          this.elements.outputPath.title = data.path;
        }
        this.showNotification('Output folder updated', 'success');
        this.closeFolderModal();
      } else {
        this.showNotification(data.error || 'Invalid path', 'error');
      }
    } catch (err) {
      this.showNotification('Error validating path: ' + err.message, 'error');
    }
  },

  truncatePath(path, maxLen = 45) {
    if (!path || path.length <= maxLen) return path;
    return '...' + path.slice(-(maxLen - 3));
  },

  formatDuration(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '';
    const s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s}s`;
    if (s < 3600) {
      const m = Math.floor(s / 60);
      const rem = s % 60;
      return rem ? `${m}m ${rem}s` : `${m}m`;
    }
    const h = Math.floor(s / 3600);
    const rem = s % 3600;
    const m = Math.floor(rem / 60);
    return `${h}h ${m}m`;
  },

  loadModelStats() {
    try {
      const raw = localStorage.getItem('yww_rtf_stats');
      this.rtfStats = raw ? JSON.parse(raw) : {};
    } catch {
      this.rtfStats = {};
    }
  },

  saveModelStats() {
    try {
      localStorage.setItem('yww_rtf_stats', JSON.stringify(this.rtfStats));
    } catch {
      /* ignore */
    }
  },

  recordRtf(model, rtf) {
    if (!model || !rtf || Number.isNaN(rtf)) return;
    if (!this.rtfStats[model]) {
      this.rtfStats[model] = [];
    }
    const arr = this.rtfStats[model];
    arr.push(rtf);
    while (arr.length > 10) arr.shift();
    this.saveModelStats();
  },

  medianRtf(model) {
    const arr = this.rtfStats[model] || [];
    if (!arr.length) {
      const defaults = { tiny: 4.0, base: 2.0, small: 1.2, medium: 0.8, large: 0.5 };
      return defaults[model] || 1.0;
    }
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  },

  audioDurationSeconds(job) {
    const audioEvent = job.events?.find(e => e.event === 'transcribe_audio_loaded');
    if (audioEvent?.duration_seconds) return audioEvent.duration_seconds;
    if (job.result?.meta?.duration) return job.result.meta.duration;
    return null;
  },

  estimateTranscribeTotal(job) {
    const dur = this.audioDurationSeconds(job);
    if (!dur) return null;
    const rtf = this.medianRtf(job.model || 'tiny');
    return dur / rtf;
  },

  loadHistory() {
    try {
      const raw = localStorage.getItem('yww_history');
      this.history = raw ? JSON.parse(raw) : [];
      this.renderHistory();
    } catch {
      this.history = [];
    }
  },

  saveHistoryEntry(job) {
    if (!job) return;
    const entry = {
      id: job.id,
      url: job.url,
      title: job.title,
      status: job.status,
      model: job.model,
      lang: job.lang,
      startTime: job.startTime,
      endTime: job.endTime,
      out: job.out,
      transcript: job.result?.transcript,
      file: job.result?.file,
      finishedAt: Date.now(),
    };
    this.history = [entry, ...this.history].slice(0, 20);
    try {
      localStorage.setItem('yww_history', JSON.stringify(this.history));
    } catch {
      /* ignore */
    }
    this.renderHistory();
  },

  recordHistory(job) {
    this.saveHistoryEntry(job);
  },

  renderHistory() {
    const list = document.getElementById('history-list');
    if (!list) return;
    if (!this.history.length) {
      list.innerHTML = `<div class="history-empty">No history yet</div>`;
      return;
    }
    list.innerHTML = this.history.map((h, i) => `
      <div class="history-item">
        <div class="history-title">${this.escapeHtml(h.title || h.url || 'Job')}</div>
        <div class="history-meta">
          <span>${this.escapeHtml(h.model || 'tiny')}</span>
          ${h.startTime ? `<span>${h.startTime}${h.endTime ? ' - ' + h.endTime : ''}</span>` : ''}
        </div>
        <div class="history-actions">
          <button class="link-btn" onclick="App.applyHistory(${i})">Use</button>
          ${h.transcript ? `<button class="link-btn" onclick="App.openFile('${this.escapeJs(h.transcript)}')">Open</button>` : ''}
        </div>
      </div>
    `).join('');
  },

  applyHistory(idx) {
    const h = this.history[idx];
    if (!h) return;
    if (this.elements.urlInput) {
      this.elements.urlInput.value = h.url || '';
      this.elements.urlInput.focus();
    }
    if (this.elements.modelSelect) {
      // Map model back to quick selector when possible
      const val = h.model || 'tiny';
      const quick = { tiny: 'Fast', base: 'Balanced', small: 'Best' };
      this.elements.modelSelect.value = quick[val] ? quick[val] : val;
    }
    const adv = document.getElementById('model-advanced');
    if (adv) adv.value = h.model || 'tiny';
    if (h.startTime) {
      this.timestampMode = true;
      this.elements.timestampPanel?.classList.add('open');
      if (this.elements.startTime) this.elements.startTime.value = h.startTime;
      if (this.elements.endTime) this.elements.endTime.value = h.endTime || '';
    }
    this.showHeroView();
  },

  loadJobs() {
    this.renderJobsList();
  },

  formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
      bytes /= 1024;
      i++;
    }
    return bytes.toFixed(1) + ' ' + units[i];
  },

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },

  escapeJs(str) {
    if (!str) return '';
    return String(str)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '\\"');
  },

  showNotification(message, type = 'info') {
    const toast = this.elements.toast || document.getElementById('toast');
    if (!toast) {
      console.log(`[${type}] ${message}`);
      return;
    }

    toast.textContent = message;
    toast.className = `toast toast-${type} show`;

    setTimeout(() => {
      toast.classList.remove('show');
    }, 3000);
  },
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
