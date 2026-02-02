const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const jobsContainer = document.getElementById('jobs');
const resultsTable = document.getElementById('results');
const onlyAztecToggle = document.getElementById('onlyAztec');
const limitsLabel = document.getElementById('limits');

let queuedFiles = [];
let activeJobs = new Map();

function updateLimits() {
  fetch('/api/limits')
    .then((res) => res.json())
    .then((data) => {
      limitsLabel.textContent = `Limit: ${data.max_file_size_mb}MB, ${data.max_pages} stron, timeout ${data.job_timeout_seconds}s`;
    })
    .catch(() => {
      limitsLabel.textContent = '';
    });
}

function renderJobs() {
  if (activeJobs.size === 0) {
    jobsContainer.innerHTML = '<p class="muted">Brak aktywnych jobów.</p>';
    return;
  }

  const html = Array.from(activeJobs.values())
    .map((job) => {
      const progress = job.progress || { done: 0, total: 0, note: '' };
      const percent = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
      return `
        <div class="job">
          <div>
            <strong>${job.id}</strong>
            <span class="badge ${job.status}">${job.status}</span>
          </div>
          <div class="progress">
            <div class="bar" style="width: ${percent}%"></div>
          </div>
          <div class="muted">${progress.note || ''}</div>
          <div class="job-actions">
            <a href="/api/jobs/${job.id}/download?fmt=json" target="_blank">JSON</a>
            <a href="/api/jobs/${job.id}/download?fmt=csv" target="_blank">CSV</a>
          </div>
        </div>
      `;
    })
    .join('');

  jobsContainer.innerHTML = html;
}

function appendResults(rows) {
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.file || ''}</td>
      <td>${row.page || ''}</td>
      <td>${row.format || ''}</td>
      <td><span class="text-cell">${row.text || ''}</span></td>
      <td><button class="copy-btn">Kopiuj</button></td>
    `;
    tr.querySelector('.copy-btn').addEventListener('click', () => {
      navigator.clipboard.writeText(row.text || '');
    });
    resultsTable.appendChild(tr);
  });
}

function pollJob(jobId) {
  fetch(`/api/jobs/${jobId}`)
    .then((res) => res.json())
    .then((data) => {
      activeJobs.set(jobId, { id: jobId, ...data });
      renderJobs();

      if (data.status === 'finished') {
        if (Array.isArray(data.result)) {
          appendResults(data.result);
        }
        activeJobs.delete(jobId);
        renderJobs();
        return;
      }

      if (data.status === 'failed') {
        activeJobs.delete(jobId);
        renderJobs();
        return;
      }

      setTimeout(() => pollJob(jobId), 1500);
    })
    .catch(() => {
      setTimeout(() => pollJob(jobId), 2000);
    });
}

function handleFiles(files) {
  queuedFiles = Array.from(files);
}

function setupDropzone() {
  dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    dropzone.classList.add('active');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('active');
  });

  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('active');
    handleFiles(event.dataTransfer.files);
  });

  fileInput.addEventListener('change', (event) => {
    handleFiles(event.target.files);
  });
}

function uploadFiles() {
  if (!queuedFiles.length) {
    alert('Wybierz pliki PDF.');
    return;
  }

  const formData = new FormData();
  queuedFiles.forEach((file) => formData.append('files', file));
  formData.append('only_aztec', onlyAztecToggle.checked ? 'true' : 'false');

  uploadBtn.disabled = true;
  fetch('/api/jobs', {
    method: 'POST',
    body: formData,
  })
    .then((res) => {
      if (!res.ok) {
        return res.json().then((data) => {
          throw new Error(data.detail || 'Upload failed');
        });
      }
      return res.json();
    })
    .then((data) => {
      const ids = data.job_ids || [];
      ids.forEach((id) => {
        activeJobs.set(id, { id, status: 'queued', progress: { done: 0, total: 0, note: '' } });
        pollJob(id);
      });
      queuedFiles = [];
    })
    .catch((err) => {
      alert(err.message);
    })
    .finally(() => {
      uploadBtn.disabled = false;
    });
}

setupDropzone();
updateLimits();
renderJobs();

uploadBtn.addEventListener('click', uploadFiles);
