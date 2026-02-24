/**
 * PICS Drug Sheet Generator — Frontend Logic
 */

const form = document.getElementById('generate-form');
const generateBtn = document.getElementById('generate-btn');
const progressSection = document.getElementById('progress-section');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const flagsSection = document.getElementById('flags-section');
const flagsList = document.getElementById('flags-list');
const downloadSection = document.getElementById('download-section');
const downloadMd = document.getElementById('download-md');
const downloadJson = document.getElementById('download-json');
const emptyState = document.getElementById('empty-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const resultsSection = document.getElementById('results-section');
const markdownOutput = document.getElementById('markdown-output');
const jsonOutput = document.getElementById('json-output');
const rawOutput = document.getElementById('raw-output');

// ---------------------------------------------------------------------------
// BNF drug name autocomplete
// ---------------------------------------------------------------------------
const drugNameInput = document.getElementById('drug-name');
const suggestionsEl = document.getElementById('drug-suggestions');
let searchTimeout = null;

drugNameInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = drugNameInput.value.trim();
    if (q.length < 2) {
        suggestionsEl.classList.add('hidden');
        return;
    }
    searchTimeout = setTimeout(async () => {
        try {
            const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const data = await resp.json();
            if (data.results && data.results.length > 0) {
                suggestionsEl.innerHTML = '';
                data.results.forEach(item => {
                    const li = document.createElement('li');
                    li.textContent = item.name;
                    li.className = 'px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 hover:text-blue-700';
                    li.addEventListener('click', () => {
                        drugNameInput.value = item.name;
                        suggestionsEl.classList.add('hidden');
                    });
                    suggestionsEl.appendChild(li);
                });
                suggestionsEl.classList.remove('hidden');
            } else {
                suggestionsEl.classList.add('hidden');
            }
        } catch {
            suggestionsEl.classList.add('hidden');
        }
    }, 250);
});

// Hide suggestions when clicking outside
document.addEventListener('click', (e) => {
    if (!drugNameInput.contains(e.target) && !suggestionsEl.contains(e.target)) {
        suggestionsEl.classList.add('hidden');
    }
});

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Deactivate all tabs
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('active', 'border-blue-600', 'text-blue-700');
            b.classList.add('border-transparent', 'text-gray-500');
        });
        document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));

        // Activate clicked tab
        btn.classList.add('active', 'border-blue-600', 'text-blue-700');
        btn.classList.remove('border-transparent', 'text-gray-500');
        const tabId = 'tab-' + btn.dataset.tab;
        document.getElementById(tabId).classList.remove('hidden');
    });
});

// ---------------------------------------------------------------------------
// Form submission
// ---------------------------------------------------------------------------
form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const drugName = document.getElementById('drug-name').value.trim();
    if (!drugName) return;

    // Reset UI
    generateBtn.disabled = true;
    generateBtn.textContent = 'Generating...';
    progressSection.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressText.textContent = 'Starting...';
    flagsSection.classList.add('hidden');
    downloadSection.classList.add('hidden');
    emptyState.classList.add('hidden');
    errorState.classList.add('hidden');
    resultsSection.classList.add('hidden');

    // Build form data
    const formData = new FormData();
    formData.append('drug_name', drugName);
    const drugForm = document.getElementById('drug-form').value.trim();
    if (drugForm) formData.append('drug_form', drugForm);

    const pdfInput = document.getElementById('pdf-upload');
    if (pdfInput.files.length > 0) {
        for (const file of pdfInput.files) {
            formData.append('pdfs', file);
        }
    }

    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            throw new Error(`Server error: ${response.status} ${response.statusText}`);
        }

        // Manual SSE parsing from ReadableStream (needed for POST requests)
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = '';

            let currentEvent = null;
            let currentData = null;

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];

                if (line.startsWith('event: ')) {
                    currentEvent = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    currentData = line.slice(6);
                } else if (line === '' && currentEvent && currentData) {
                    // Complete event — process it
                    handleSSEEvent(currentEvent, currentData);
                    currentEvent = null;
                    currentData = null;
                } else if (line !== '') {
                    // Incomplete event, put back in buffer
                    buffer = lines.slice(i).join('\n');
                    break;
                }
            }
        }

    } catch (err) {
        showError(err.message);
    } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate Drug Sheet';
    }
});

// ---------------------------------------------------------------------------
// SSE event handler
// ---------------------------------------------------------------------------
function handleSSEEvent(event, dataStr) {
    let data;
    try {
        data = JSON.parse(dataStr);
    } catch {
        return;
    }

    switch (event) {
        case 'progress':
            updateProgress(data.message, data.percent);
            break;
        case 'complete':
            onComplete(data);
            break;
        case 'error':
            showError(data.message);
            break;
    }
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------
function updateProgress(message, percent) {
    progressBar.style.width = percent + '%';
    progressText.textContent = message;
}

function showError(message) {
    errorState.classList.remove('hidden');
    errorMessage.textContent = message;
    progressSection.classList.add('hidden');
}

function onComplete(data) {
    // Hide progress, show results
    progressSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    // Render markdown
    markdownOutput.innerHTML = marked.parse(data.markdown);

    // Render JSON
    jsonOutput.textContent = JSON.stringify(data.epma_json, null, 2);
    syntaxHighlight(jsonOutput);

    // Render raw data
    rawOutput.textContent = JSON.stringify(data.raw_data, null, 2);
    syntaxHighlight(rawOutput);

    // Activate first tab
    document.querySelector('[data-tab="review"]').click();

    // Download links
    downloadSection.classList.remove('hidden');
    downloadMd.href = `/api/download/${data.id}/markdown`;
    downloadJson.href = `/api/download/${data.id}/json`;

    // Human review flags
    const flags = data.human_review_flags || [];
    if (flags.length > 0) {
        flagsSection.classList.remove('hidden');
        flagsList.innerHTML = '';
        flags.forEach(flag => {
            const li = document.createElement('li');
            li.className = 'flex items-start gap-1.5';
            li.innerHTML = `<span class="text-amber-500 mt-0.5 flex-shrink-0">&#9679;</span><span>${escapeHtml(flag)}</span>`;
            flagsList.appendChild(li);
        });
    }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function syntaxHighlight(pre) {
    let html = pre.textContent;
    // Basic JSON syntax colouring
    html = html.replace(/("(\\.|[^"\\])*")\s*:/g, '<span class="json-key">$1</span>:');
    html = html.replace(/:\s*("(\\.|[^"\\])*")/g, ': <span class="json-string">$1</span>');
    html = html.replace(/:\s*(\d+(\.\d+)?)/g, ': <span class="json-number">$1</span>');
    html = html.replace(/:\s*(true|false|null)/g, ': <span class="json-bool">$1</span>');
    pre.innerHTML = html;
}
