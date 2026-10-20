/* selfOCR フロントエンド */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const state = {
    docId: null,
    pages: 0,
    page: 0,
    results: [],
    crop: { image: null, selection: null },
    busy: false,
  };

  // ---------- 補助 ----------
  async function api(path, options = {}) {
    const res = await fetch(path, options);
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { error: text }; }
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  let toastTimer = null;
  function toast(message, kind = '') {
    const el = $('toast');
    el.textContent = message;
    el.className = 'toast' + (kind ? ' is-' + kind : '');
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
  }

  function options() {
    return {
      mode: $('opt-mode').value,
      dpi: parseFloat($('opt-dpi').value),
      math: $('opt-math').checked,
      furniture: $('opt-furniture').checked,
      strip_html: $('opt-strip-html').checked,
      image_ocr: true,
    };
  }

  function setProgress(done, total, text) {
    const box = $('progress');
    if (done === null) { box.classList.add('is-hidden'); return; }
    box.classList.remove('is-hidden');
    $('progress-bar').style.width = total ? Math.round((done / total) * 100) + '%' : '0%';
    $('progress-text').textContent = text;
  }

  function bytesLabel(n) {
    if (!n && n !== 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
  }

  // ---------- タブ ----------
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('is-active'));
      tab.classList.add('is-active');
      $('tab-file').classList.toggle('is-hidden', tab.dataset.tab !== 'file');
      $('tab-screen').classList.toggle('is-hidden', tab.dataset.tab !== 'screen');
    });
  });

  // ---------- ファイルアップロード ----------
  const dropzone = $('dropzone');
  const fileInput = $('file-input');

  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files[0]) uploadFile(fileInput.files[0]);
    fileInput.value = '';
  });
  ['dragenter', 'dragover'].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add('is-over');
    })
  );
  ['dragleave', 'drop'].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove('is-over');
    })
  );
  dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  async function uploadFile(file) {
    if (state.busy) return;
    state.busy = true;
    setProgress(0, 1, `${file.name} をアップロード中...`);
    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'アップロードに失敗しました');
      state.docId = data.id;
      state.pages = data.pages;
      state.page = 0;
      state.results = [];
      $('btn-rescan').disabled = false;
      $('filename').textContent = `${file.name} · ${bytesLabel(data.size)} · ${data.pages} ページ`;
      await runAllPages();
    } catch (err) {
      toast(err.message, 'err');
      setProgress(null);
    } finally {
      state.busy = false;
    }
  }

  async function runAllPages() {
    if (!state.docId) return;
    const total = state.pages;
    for (let n = 0; n < total; n += 1) {
      setProgress(n, total, `${n + 1} / ${total} ページを読み取り中...`);
      try {
        const result = await api('/api/page', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: state.docId, n, opts: options() }),
        });
        state.results[n] = result;
      } catch (err) {
        toast(`ページ ${n + 1}: ${err.message}`, 'err');
        break;
      }
    }
    setProgress(total, total, `完了 (${total} ページ)`);
    showPage(Math.min(state.page, total - 1));
  }

  // ---------- 表示 ----------
  function showPage(n) {
    const result = state.results[n];
    if (!result) return;
    state.page = n;
    $('page-label').textContent = `${n + 1} / ${state.results.length}`;
    $('btn-prev').disabled = n <= 0;
    $('btn-next').disabled = n >= state.results.length - 1;

    const text = $('out-text');
    text.innerHTML = result.html || `<pre>${escapeHtml(result.markdown || '')}</pre>`;
    text.classList.toggle('is-empty', !result.markdown);

    const timings = result.timings || {};
    const t = timings.total_ms ? `${Math.round(timings.total_ms)} ms` : '-';
    $('out-meta').innerHTML = [
      `<span class="tag">${escapeHtml(result.source || '')}</span>`,
      `<span class="tag">${t}</span>`,
      `<span class="tag">${(result.lines || []).length} 行</span>`,
      result.note ? `<span>${escapeHtml(result.note)}</span>` : '',
    ].join('');

    drawPreview(result);
  }

  function drawPreview(result) {
    const canvas = $('preview');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    img.onload = () => {
      canvas.width = img.width;
      canvas.height = img.height;
      ctx.drawImage(img, 0, 0);
      if ($('chk-boxes').checked) drawBoxes(ctx, result);
    };
    img.src = result.img;
  }

  function drawBoxes(ctx, result) {
    ctx.lineWidth = 1.5;
    ctx.font = '11px ui-monospace, monospace';
    (result.lines || []).forEach((line, i) => {
      const [x0, y0, x1, y1] = line.box;
      ctx.strokeStyle = 'rgba(47,111,235,.85)';
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.fillStyle = 'rgba(47,111,235,.9)';
      ctx.fillRect(x0, Math.max(0, y0 - 12), 14, 12);
      ctx.fillStyle = '#fff';
      ctx.fillText(String(i + 1), x0 + 3, Math.max(9, y0 - 3));
    });
    (result.blocks || []).forEach((block) => {
      const [x0, y0, x1, y1] = block.box;
      ctx.strokeStyle = 'rgba(224,120,32,.75)';
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.setLineDash([]);
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  $('btn-prev').addEventListener('click', () => showPage(state.page - 1));
  $('btn-next').addEventListener('click', () => showPage(state.page + 1));
  $('chk-boxes').addEventListener('change', () => {
    const result = state.results[state.page];
    if (result) drawPreview(result);
  });
  async function rescan() {
    if (!state.docId || state.busy) return;
    state.busy = true;
    try {
      await runAllPages();
    } finally {
      state.busy = false;
    }
  }

  $('btn-rescan').addEventListener('click', rescan);
  // HTMLタグ除去は認識結果の後処理だけなので, すぐ反映する.
  $('opt-strip-html').addEventListener('change', rescan);

  // ---------- テンポラリデータ削除 ----------
  function clearDocument() {
    state.docId = null;
    state.pages = 0;
    state.page = 0;
    state.results = [];
    $('filename').textContent = '';
    $('page-label').textContent = '- / -';
    $('btn-prev').disabled = true;
    $('btn-next').disabled = true;
    $('btn-rescan').disabled = true;
    $('out-meta').innerHTML = '';
    setProgress(null);
    const text = $('out-text');
    text.textContent = '';
    text.classList.add('is-empty');
    const canvas = $('preview');
    canvas.width = 0;
    canvas.height = 0;
  }

  $('btn-cleanup').addEventListener('click', async () => {
    if (state.busy) return;
    state.busy = true;
    const btn = $('btn-cleanup');
    btn.classList.add('is-busy');
    try {
      const res = await api('/api/cleanup', { method: 'POST' });
      clearDocument();
      toast(`テンポラリデータを削除しました (${res.removed} 件)`, 'ok');
    } catch (err) {
      toast(err.message, 'err');
    } finally {
      btn.classList.remove('is-busy');
      state.busy = false;
    }
  });

  // ---------- コピー / 保存 ----------
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('コピーしました', 'ok');
    } catch (_) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        toast('コピーしました', 'ok');
      } catch (err) {
        toast('コピーに失敗しました', 'err');
      }
      document.body.removeChild(ta);
    }
  }

  $('btn-copy').addEventListener('click', () => {
    const result = state.results[state.page];
    if (!result) return toast('コピーする内容がありません', 'err');
    copyText(result.markdown || result.text || '');
  });

  function download(name, content, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function baseName() {
    const result = state.results[state.page];
    const raw = (result && result.name) || 'selfocr';
    const clean = String(raw).replace(/\.[^.]+$/, '').replace(/[^\w.\-]+/g, '_');
    return clean || 'selfocr';
  }

  $('btn-md').addEventListener('click', () => {
    const result = state.results[state.page];
    if (!result) return toast('保存する内容がありません', 'err');
    download(`${baseName()}_p${state.page + 1}.md`, result.markdown || '', 'text/markdown');
  });
  $('btn-txt').addEventListener('click', () => {
    const result = state.results[state.page];
    if (!result) return toast('保存する内容がありません', 'err');
    download(`${baseName()}_p${state.page + 1}.txt`, result.text || '', 'text/plain');
  });
  $('btn-json').addEventListener('click', () => {
    const result = state.results[state.page];
    if (!result) return toast('保存する内容がありません', 'err');
    download(`${baseName()}_p${state.page + 1}.json`, JSON.stringify(result.json, null, 2), 'application/json');
  });

  // ---------- 画面キャプチャ ----------
  const cropCanvas = $('crop-canvas');
  const cropStage = $('crop-stage');
  const cropSel = $('crop-sel');

  function setCaptureNote(text, warn) {
    const el = $('capture-note');
    el.textContent = text;
    el.classList.toggle('is-warn', !!warn);
  }

  function loadCaptureImage(source, label) {
    const img = new Image();
    img.onload = () => {
      cropCanvas.width = img.naturalWidth;
      cropCanvas.height = img.naturalHeight;
      const ctx = cropCanvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      cropStage.classList.remove('is-empty');
      $('crop-empty').style.display = 'none';
      state.crop.image = img;
      state.crop.selection = null;
      cropSel.classList.remove('is-on');
      $('btn-scan-crop').disabled = false;
      $('chk-crop-sel').checked = true;
      setCaptureNote(`${label} · ${img.naturalWidth}×${img.naturalHeight} · 範囲をドラッグして選ぶ`, false);
    };
    img.onerror = () => setCaptureNote('画像を読み込めませんでした', true);
    img.src = source;
  }

  async function captureScreen() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      setCaptureNote(
        'この接続では画面キャプチャを使えません。https:// または http://localhost で開くと利用できます。' +
        'Clipboard への貼り付け (Ctrl+V) でも同じ操作ができます。',
        true
      );
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: { cursor: 'always' }, audio: false });
    } catch (err) {
      setCaptureNote(`キャプチャを中止しました (${err.message})`, true);
      return;
    }
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((resolve) => {
      if (video.videoWidth) resolve();
      else video.addEventListener('loadeddata', resolve, { once: true });
    });
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    stream.getTracks().forEach((t) => t.stop());
    loadCaptureImage(canvas.toDataURL('image/png'), '画面をキャプチャしました');
  }

  $('btn-capture').addEventListener('click', captureScreen);
  $('btn-paste-hint').addEventListener('click', () => {
    setCaptureNote('クリップボードの画像を Ctrl+V (Mac は ⌘+V) で貼り付けてください', false);
    $('crop-stage').focus();
  });

  // 貼り付け (クリップボードの画像)
  document.addEventListener('paste', (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      if (item.type && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          const reader = new FileReader();
          reader.onload = () => loadCaptureImage(reader.result, 'クリップボードの画像');
          reader.readAsDataURL(file);
          return;
        }
      }
    }
  });

  // 範囲選択
  let dragging = null;
  cropCanvas.addEventListener('mousedown', (e) => {
    if (!state.crop.image) return;
    const rect = cropCanvas.getBoundingClientRect();
    dragging = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    cropSel.classList.add('is-on');
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const rect = cropCanvas.getBoundingClientRect();
    const stage = cropStage.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const left = Math.min(dragging.x, x);
    const top = Math.min(dragging.y, y);
    const width = Math.abs(x - dragging.x);
    const height = Math.abs(y - dragging.y);
    // .crop-sel は .crop-stage 基準なので, キャンバスとの差分を足す
    cropSel.style.left = `${rect.left - stage.left + left}px`;
    cropSel.style.top = `${rect.top - stage.top + top}px`;
    cropSel.style.width = `${width}px`;
    cropSel.style.height = `${height}px`;
    state.crop.selection = { left, top, width, height, scale: cropCanvas.width / rect.width };
  });
  window.addEventListener('mouseup', () => { dragging = null; });

  $('btn-scan-crop').addEventListener('click', async () => {
    if (!state.crop.image) return toast('先に画面をキャプチャしてください', 'err');
    const canvas = cropCanvas;
    let sx = 0, sy = 0, sw = canvas.width, sh = canvas.height;
    const sel = state.crop.selection;
    if ($('chk-crop-sel').checked && sel && sel.width > 4 && sel.height > 4) {
      sx = Math.max(0, Math.round(sel.left * sel.scale));
      sy = Math.max(0, Math.round(sel.top * sel.scale));
      sw = Math.min(canvas.width - sx, Math.round(sel.width * sel.scale));
      sh = Math.min(canvas.height - sy, Math.round(sel.height * sel.scale));
    }
    const out = document.createElement('canvas');
    out.width = sw;
    out.height = sh;
    out.getContext('2d').drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);
    const blob = await new Promise((resolve) => out.toBlob(resolve, 'image/png'));
    if (!blob) return toast('画像を作成できませんでした', 'err');
    const file = new File([blob], `capture-${Date.now()}.png`, { type: 'image/png' });
    uploadFile(file);
  });

  // ---------- アップデート / 再起動 ----------
  const modal = $('modal');
  $('modal-close').addEventListener('click', () => modal.classList.add('is-hidden'));

  function openModal(title, body) {
    $('modal-title').textContent = title;
    $('modal-body').textContent = body;
    modal.classList.remove('is-hidden');
  }

  async function waitForService(timeoutMs = 120000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        if (res.ok) return true;
      } catch (_) { /* 再起動中 */ }
      await new Promise((r) => setTimeout(r, 800));
    }
    return false;
  }

  $('btn-update').addEventListener('click', async () => {
    const btn = $('btn-update');
    btn.classList.add('is-busy');
    openModal('アップデート', '開始しています...');
    try {
      await api('/api/update', { method: 'POST' });
      let last = '';
      for (;;) {
        let status;
        try {
          status = await api('/api/update/status');
        } catch (_) {
          await new Promise((r) => setTimeout(r, 1200));
          continue;
        }
        const lines = [];
        (status.steps || []).forEach((s) => {
          const mark = { running: '…', done: '✓', error: '×' }[s.state] || '·';
          lines.push(`${mark} ${s.name}${s.output ? ` — ${s.output}` : ''}`);
        });
        const text = lines.join('\n') + (status.message ? `\n\n${status.message}` : '');
        if (text !== last) {
          $('modal-body').textContent = text;
          last = text;
        }
        if (status.state === 'error') {
          toast(status.message || 'アップデートに失敗しました', 'err');
          break;
        }
        if (status.state === 'done') {
          $('modal-body').textContent += '\n\n再起動しています...';
          const back = await waitForService();
          toast(back ? 'アップデートが完了しました' : '再起動に時間がかかっています', back ? 'ok' : '');
          break;
        }
        if (status.state === 'idle') {
          // サービスが再起動した (状態が保存されていない場合)
          const back = await waitForService();
          toast(back ? 'アップデートが完了しました' : '再起動に時間がかかっています', back ? 'ok' : '');
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (err) {
      toast(err.message, 'err');
    } finally {
      btn.classList.remove('is-busy');
      setTimeout(() => modal.classList.add('is-hidden'), 1200);
    }
  });

  $('btn-restart').addEventListener('click', async () => {
    const btn = $('btn-restart');
    btn.classList.add('is-busy');
    try {
      await api('/api/restart', { method: 'POST' });
      toast('再起動しています...');
      const back = await waitForService(30000);
      if (back) {
        toast('再起動しました', 'ok');
        window.location.reload();
      } else {
        toast('再起動に時間がかかっています', '');
      }
    } catch (err) {
      toast(err.message, 'err');
    } finally {
      btn.classList.remove('is-busy');
    }
  });

  // ---------- 起動時 ----------
  (async () => {
    try {
      const info = await api('/api/info');
      if (info.version_label) $('version').textContent = info.version_label;
      document.title = `${info.name || 'selfOCR'} ${info.version_label || ''}`.trim();
      if (info.repo) {
        $('btn-update').title = `${info.repo} から最新版に更新します`;
      }
      setCaptureNote(
        navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia
          ? '「画面をキャプチャ」で任意の画面を取り込み、範囲を選んでスキャンできます。'
          : '画面キャプチャはこの接続では使えません (https:// または localhost 経由でアクセスしてください)。貼り付け (Ctrl+V) は利用できます。',
        !(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia)
      );
    } catch (_) {
      /* 情報の取得に失敗しても操作は続けられる */
    }
  })();
})();
