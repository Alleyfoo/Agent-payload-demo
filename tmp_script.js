
        const agentDetectionRules = [
          { target: 'header', keywords: ['header', 'headers', 'otsikko', 'sarake', 'column names', 'normalize headers'] },
          { target: 'schema', keywords: ['schema', 'scheman', 'rakenne', 'structure', 'schema agent'] },
          { target: 'transform', keywords: ['transform', 'convert', 'muunna', 'muunnos', 'transform agent', 'normalize'] },
          { target: 'save', keywords: ['save', 'export', 'output_dir', 'tallenna', 'write file', 'output file'] },
        ];

        function detectTargetAgent(message) {
          const normalized = (message || '').toLowerCase();
          for (const rule of agentDetectionRules) {
            if (rule.keywords.some((keyword) => normalized.includes(keyword))) {
              return rule.target;
            }
          }
          return null;
        }

        function updateAgentPanel(target, data) {
          const panel = document.getElementById(`${target}-output`);
          if (!panel) {
            return;
          }
          panel.textContent = JSON.stringify(data, null, 2);
          panel.scrollTop = panel.scrollHeight;
        }

        function formatAgentMessage(agent, data) {
          if (!data) return "";
          if (agent === "header" && data.schema && Array.isArray(data.schema.columns)) {
            const cols = data.schema.columns.map((c) => c.raw_name || c.canonical_name || "").filter(Boolean);
            const renamed = Object.entries(data.rename_map || {})
              .map(([raw, canonical]) => `${raw} â†’ ${canonical}`)
              .join(", ");
            const lines = [];
            if (cols.length) {
              lines.push(`Header-agentti lÃ¶ysi sarakkeet: ${cols.join(", ")}.`);
            }
            if (renamed) {
              lines.push(`Normalisoinnit: ${renamed}.`);
            }
            return lines.join(" ");
          }
          return "";
        }

        async function send() {
          const msg = document.getElementById('message').value.trim();
          if (!msg) return;
          const taskType = document.getElementById('taskType').value;
          const manualTarget = document.getElementById('targetAgent').value || 'speaker';
          let target = manualTarget;
          if (manualTarget === 'speaker') {
            const autoTarget = detectTargetAgent(msg);
            if (autoTarget) {
              target = autoTarget;
            }
          }
          const agentLabel = manualTarget === 'speaker' && target !== manualTarget ? `${manualTarget} -> ${target}` : target;
          let endpoint = '/chat/hybrid';
          let payload = {};
          if (target === 'speaker') {
            payload = { message: msg, task_type: taskType || null };
          } else {
            // Data-agentit: try JSON parsing, otherwise fall back to a simple payload
            try {
              payload = JSON.parse(msg);
            } catch (e) {
              if (target === 'header' || target === 'schema') {
                payload = { headers: [msg] }; // fallback: treat input as a header name
              } else {
                payload = { message: msg };
              }
            }
          }
          if (target === 'speaker') {
            endpoint = '/chat/hybrid';
          } else if (target === 'header') {
            endpoint = '/chat/header_agent';
          } else if (target === 'schema') {
            endpoint = '/chat/schema_agent';
          } else if (target === 'transform') {
            endpoint = '/chat/transform_agent';
          } else if (target === 'save') {
            endpoint = '/chat/save_agent';
          }

          const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const errText = await res.text();
            document.getElementById('response').textContent = 'Error ' + res.status + ': ' + errText;
            return;
          }
          const data = await res.json();
          const responseNode = document.getElementById('response');
          const agentSummary = formatAgentMessage(target, data);
          responseNode.textContent = `Agent: ${agentLabel}\n${JSON.stringify(data, null, 2)}`;
          if (agentSummary) {
            responseNode.textContent = `Agent: ${agentLabel}\n${agentSummary}\n\n${JSON.stringify(data, null, 2)}`;
          }
          responseNode.scrollTop = responseNode.scrollHeight;
          updateAgentPanel(target, data);
        }
        document.getElementById('send').addEventListener('click', send);
        document.getElementById('message').addEventListener('keydown', (e) => {
          if (e.ctrlKey && e.key === 'Enter') send();
        });

        async function sendHeader(payloadOverride) {
          let payload = payloadOverride;
          if (!payload) {
            const text = document.getElementById('header-input').value;
            try {
              payload = JSON.parse(text);
            } catch (e) {
              document.getElementById('header-output').textContent = 'Virhe: ' + e;
              return;
            }
          }
          const res = await fetch('/chat/header_agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const errText = await res.text();
            document.getElementById('header-output').textContent = 'Virhe: ' + res.status + ': ' + errText;
            return;
          }
          const data = await res.json();
          updateAgentPanel('header', data);
          document.getElementById('header-output').textContent = JSON.stringify(data, null, 2);
          document.getElementById('header-output').scrollTop = document.getElementById('header-output').scrollHeight;
          const responseNode = document.getElementById('response');
          const summary = formatAgentMessage('header', data);
          const headerLabel = 'header';
          responseNode.textContent = `Agent: ${headerLabel}\n${summary ? summary + "\n\n" : ""}${JSON.stringify(data, null, 2)}`;
          responseNode.scrollTop = responseNode.scrollHeight;
        }

        async function readHeaderFile() {
          const fileInput = document.getElementById('header-file');
          if (!fileInput.files || !fileInput.files[0]) {
            document.getElementById('header-output').textContent = 'Valitse tiedosto ensin.';
            return;
          }
          const formData = new FormData();
          formData.append('file', fileInput.files[0]);
          try {
            const res = await fetch('/chat/inspect_headers', {
              method: 'POST',
              body: formData,
            });
            const out = document.getElementById('header-output');
            if (!res.ok) {
              const txt = await res.text();
              out.textContent = 'Virhe: ' + res.status + ' ' + txt;
              return;
            }
            const data = await res.json();
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
            const payload = { headers: data.columns };
            document.getElementById('header-input').value = JSON.stringify(payload, null, 2);
            await sendHeader(payload);
          } catch (e) {
            document.getElementById('header-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendSchema() {
          const text = document.getElementById('schema-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/schema_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('schema-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('schema-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendTransform() {
          const text = document.getElementById('transform-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/transform_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('transform-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('transform-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendSave() {
          const text = document.getElementById('save-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/save_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('save-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('save-output').textContent = 'Virhe: ' + e;
          }
        }
      