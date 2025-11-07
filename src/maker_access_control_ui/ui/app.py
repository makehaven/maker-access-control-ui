# noqa: D101,D102,D103
"""Maker Access Control UI application."""

import logging
import os
import re
import uuid
from http import HTTPStatus
from typing import Any
from typing import Dict

from quart import Quart
from quart import Response
from quart import jsonify
from quart import render_template_string
from quart import request
from markupsafe import Markup

from maker_access_control_ui.access.provider import AccessProvider
from maker_access_control_ui.access.provider import get_provider
from maker_access_control_ui.config import CONFIG


app = Quart(__name__)
logger = logging.getLogger(__name__)

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Maker Access Control</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 1.5rem; color: #222; }
    h1 { margin-top: 0; }
    h2 { margin-bottom: 0.75rem; }
    .intro { background: #fff; border-radius: 8px; padding: 1rem 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 1.5rem; }
    .intro p { margin: 0.35rem 0; }
    .tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
    .tabs button { padding: 0.45rem 1rem; border: none; border-radius: 999px; background: #dee2e6; color: #1f2933; cursor: pointer; font-weight: 600; }
    .tabs button.active { background: #0b7285; color: #fff; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .grid { display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); }
    section { background: #fff; border-radius: 8px; padding: 1rem 1.25rem 1.25rem; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
    form { display: grid; gap: 0.5rem; margin-bottom: 1rem; }
    form .row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    input, select { flex: 1 1 48%; padding: 0.45rem 0.5rem; border: 1px solid #ccc; border-radius: 4px; }
    label { width: 100%; font-size: 0.85rem; color: #555; }
    form button { justify-self: flex-start; padding: 0.45rem 0.9rem; background: #0b7285; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { border-bottom: 1px solid #e6e6e6; padding: 0.45rem 0.25rem; text-align: left; vertical-align: top; }
    tr:last-child td { border-bottom: none; }
    button.action { background: transparent; color: #b00020; border: none; cursor: pointer; padding: 0; font-size: 0.85rem; }
    button.action:hover { text-decoration: underline; }
    .status { margin-bottom: 1rem; min-height: 1.2em; font-weight: 600; }
    .status.error { color: #c92a2a; }
    .status.success { color: #2f9e44; }
    .filters { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
    pre { background: #1e1e1e; color: #f8f8f2; padding: 0.75rem; border-radius: 6px; overflow: auto; font-size: 0.9rem; }
    .empty { color: #777; font-style: italic; }
    details { background: #f8f9fa; border-radius: 6px; padding: 0.5rem 0.75rem; }
    details summary { cursor: pointer; font-weight: 600; }
    details .row { margin-top: 0.5rem; }
    .block-label { font-weight: 600; margin-bottom: 0.25rem; display: block; }
    .muted { color: #6b7280; font-size: 0.75rem; display: block; margin-top: 0.15rem; }
    .helper-text { color: #4b5563; font-size: 0.85rem; margin: 0 0 0.75rem; }
  </style>
</head>
<body>
  <h1>Maker Access Control</h1>
  <div class="intro">
    <p><strong>What this is:</strong> a lightweight admin surface that replaces Drupal for test environments or simple deployments. It stores data in JSON so you can iterate quickly.</p>
    <p><strong>Persistence:</strong> {{ persistence_note }}</p>
    <p><strong>Workflow:</strong> 1) add people &amp; assign card serials, 2) register permissions by badge text (IDs/devices fill in automatically), 3) grant access, 4) use the simulator to inspect API responses or swipe behavior.</p>
  </div>
  <nav class="tabs">
    <button type="button" class="tab-button active" data-tab="admin">User &amp; Permission Admin</button>
    <button type="button" class="tab-button" data-tab="sim">Simulator</button>
  </nav>
  <p class="status" id="status"></p>
  <div id="tab-admin" class="tab-panel active">
    <div class="grid">
    <section>
      <h2>People</h2>
      <form id="user-form">
        <input type="hidden" name="user_id" />
        <div class="row">
          <label>First name
            <input name="first_name" placeholder="Alice" />
          </label>
          <label>Last name
            <input name="last_name" placeholder="Anderson" />
          </label>
        </div>
        <div class="row">
          <label>Email
            <input name="email" placeholder="alice@example.com" />
          </label>
          <label>Card serial (hexadecimal)
            <input name="card_serial" placeholder="01020304" required />
          </label>
        </div>
        <details>
          <summary>Advanced (optional)</summary>
          <div class="row">
            <label>UUID (optional)
              <input name="uuid" placeholder="11111111-1111-1111-1111-111111111111" />
            </label>
          </div>
        </details>
        <button type="submit">Add or Update User</button>
      </form>
      <table>
        <thead>
          <tr><th>UUID</th><th>First</th><th>Last</th><th>Email</th><th>Card Serial</th><th></th></tr>
        </thead>
        <tbody id="users-body"></tbody>
      </table>
    </section>

    <section>
      <h2>Permissions</h2>
      <p class="helper-text">Define the badge or permission text your website checks. Internal IDs are generated automatically.</p>
      <form id="tool-form">
        <input type="hidden" name="tool_id" />
        <label>Permission ID (badge text ID)
          <input name="permission_id" placeholder="laser" required />
        </label>
        <label>Display name
          <input name="name" placeholder="Laser Cutter" />
        </label>
        <button type="submit">Add or Update Permission</button>
      </form>
      <table>
        <thead>
          <tr><th>Permission</th><th>Display name</th><th></th></tr>
        </thead>
        <tbody id="tools-body"></tbody>
      </table>
    </section>

    <section>
      <h2>Permissions</h2>
      <form id="assign-form">
        <div class="row">
          <label>Person
            <select name="user_id" id="assign-user" required></select>
          </label>
          <label>Permission
            <select name="tool_id" id="assign-tool" required></select>
          </label>
        </div>
        <button type="submit">Grant Access</button>
      </form>
      <div class="filters">
        <label>User filter
          <select id="filter-user"></select>
        </label>
        <label>Permission filter
          <select id="filter-tool"></select>
        </label>
      </div>
      <table>
        <thead>
          <tr><th>User</th><th>Permission</th><th></th></tr>
        </thead>
        <tbody id="assign-body"></tbody>
      </table>
    </section>
    </div>
  </div>

  <div id="tab-sim" class="tab-panel">
    <section>
      <h2>Permission Endpoint Simulator</h2>
      <p class="helper-text">Call the same API URLs that the website expects and inspect the exact request and response payloads.</p>
      <p class="helper-text">Need to drive a full swipe (including Home Assistant or ESPHome devices)? Use your existing simulator scripts or call the upstream cardsystem API with a reader + card to validate the full path.</p>
      <form id="permission-form">
        <div class="row">
          <label>Card serial
            <select name="card_id" id="permission-card" required></select>
          </label>
          <label>Permission
            <select name="permission_id" id="permission-select" required></select>
          </label>
        </div>
        <button type="submit">Send Request</button>
      </form>
      <div>
        <span class="block-label">Request URL</span>
        <pre id="permission-request" class="empty">No request yet.</pre>
      </div>
      <div>
        <span class="block-label">Response (HTTP <span id="permission-status-code">-</span>)</span>
        <pre id="permission-response" class="empty">No response yet.</pre>
      </div>
      <p class="status" id="sim-status"></p>
    </section>

  </div>

  <script>
    const statusEl = document.getElementById('status');
    const simStatusEl = document.getElementById('sim-status');
    const usersBody = document.getElementById('users-body');
    const toolsBody = document.getElementById('tools-body');
    const assignBody = document.getElementById('assign-body');
    const assignUserSelect = document.getElementById('assign-user');
    const assignToolSelect = document.getElementById('assign-tool');
    const filterUser = document.getElementById('filter-user');
    const filterTool = document.getElementById('filter-tool');
    const permissionCardSelect = document.getElementById('permission-card');
    const permissionSelect = document.getElementById('permission-select');
    const permissionRequest = document.getElementById('permission-request');
    const permissionResponse = document.getElementById('permission-response');
    const permissionStatusCode = document.getElementById('permission-status-code');
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabPanels = document.querySelectorAll('.tab-panel');
    const userForm = document.getElementById('user-form');
    const toolForm = document.getElementById('tool-form');
    const assignForm = document.getElementById('assign-form');
    const permissionForm = document.getElementById('permission-form');

    let currentState = { users: [], tools: [], assignments: [], permissions: [], meta: {} };
    const permissionTemplateDefault = '/api/v0/serial/{card_serial}/permission/{permission_id}';
    const permissionEndpointTemplateRaw = {{ permission_endpoint_template | tojson }};
    const permissionEndpointTemplate = (permissionEndpointTemplateRaw || permissionTemplateDefault).trim() || permissionTemplateDefault;

    function setStatus(message, isError = false) {
      statusEl.textContent = message || '';
      statusEl.classList.remove('error', 'success');
      if (!message) {
        return;
      }
      statusEl.classList.add(isError ? 'error' : 'success');
    }

    function setSimStatus(message, isError = false) {
      simStatusEl.textContent = message || '';
      simStatusEl.classList.remove('error', 'success');
      if (!message) {
        return;
      }
      simStatusEl.classList.add(isError ? 'error' : 'success');
    }

    function clearPre(element, placeholder) {
      element.classList.add('empty');
      element.textContent = placeholder;
    }

    function slugify(value) {
      return (value || '')
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .replace(/_{2,}/g, '_');
    }

    function safeParseJson(text) {
      try {
        return JSON.parse(text);
      } catch (error) {
        return text;
      }
    }

    function formatUserDisplay(user) {
      if (!user) {
        return '';
      }
      const name = [user.first_name, user.last_name].filter(Boolean).join(' ');
      const parts = [user.uuid || user.id];
      if (name) {
        parts.push(name);
      }
      if (user.email) {
        parts.push(user.email);
      }
      if (user.card_serial) {
        parts.push(user.card_serial);
      }
      return parts.join(' · ');
    }

    function formatPermissionDisplay(tool) {
      if (!tool) {
        return '';
      }
      const parts = [tool.badge_name || tool.id];
      if (tool.name) {
        parts.push(tool.name);
      }
      return parts.join(' · ');
    }

    function populateSelect(selectEl, values, { includeAll = false, allLabel = 'All', emptyLabel = 'None' } = {}) {
      while (selectEl.firstChild) {
        selectEl.removeChild(selectEl.firstChild);
      }
      if (includeAll) {
        selectEl.appendChild(createOption('', allLabel));
      }
      if (!values.length) {
        selectEl.appendChild(createOption('', emptyLabel));
        return;
      }
      values.forEach(({ value, label }) => {
        selectEl.appendChild(createOption(value, label));
      });
    }

    function createOption(value, label) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      return option;
    }

    function activateTab(tab) {
      tabButtons.forEach((button) => {
        const isActive = (button.dataset.tab || 'admin') === tab;
        button.classList.toggle('active', isActive);
      });
      tabPanels.forEach((panel) => {
        const isActive = panel.id === 'tab-' + tab;
        panel.classList.toggle('active', isActive);
      });
    }

    function buildCardOptions() {
      return currentState.users
        .map((user) => {
          if (!user.card_serial) {
            return null;
          }
          const parts = [user.card_serial];
          const name = [user.first_name, user.last_name].filter(Boolean).join(' ');
          if (name) {
            parts.push(name);
          }
          if (user.email) {
            parts.push(user.email);
          }
          return { value: user.card_serial, label: parts.join(' · ') };
        })
        .filter(Boolean);
    }

    function buildPermissionRequest(cardSerial, permissionId) {
      const normalizedCard = (cardSerial || '').toLowerCase();
      const selectedUser = currentState.users.find(
        (user) => (user.card_serial || '').toLowerCase() === normalizedCard,
      );
      const replacements = [
        ['{card_serial}', encodeURIComponent(cardSerial)],
        ['{card_id}', encodeURIComponent(cardSerial)],
        ['{permission_id}', encodeURIComponent(permissionId)],
        ['{permission}', encodeURIComponent(permissionId)],
      ];
      let uuidValue = '';
      if (selectedUser && selectedUser.uuid) {
        uuidValue = encodeURIComponent(selectedUser.uuid);
      }
      replacements.push(['{uuid}', uuidValue]);

      let url = permissionEndpointTemplate;
      replacements.forEach(([needle, value]) => {
        if (!needle) {
          return;
        }
        url = url.split(needle).join(value);
      });

      return {
        url,
        requiresUuid: permissionEndpointTemplate.includes('{uuid}'),
        hasUuid: Boolean(uuidValue),
        selectedUser,
      };
    }

    async function loadState() {
      const res = await fetch('/api/state');
      if (!res.ok) {
        throw new Error('Failed to load state');
      }
      const data = await res.json();
      currentState = data;
      renderUsers(data.users);
      renderPermissions(data.tools);
      updateAssignmentOptions();
      updateFilters();
      renderAssignments();
      updatePermissionOptions();
    }

    function renderUsers(users) {
      if (!users.length) {
        usersBody.innerHTML = '<tr><td colspan="6" class="empty">No users yet</td></tr>';
        return;
      }
      usersBody.innerHTML = users.map((user) => {
        const uuid = user.uuid || '';
        return '<tr>' +
          '<td>' + (uuid || user.id || '') + '</td>' +
          '<td>' + (user.first_name || '') + '</td>' +
          '<td>' + (user.last_name || '') + '</td>' +
          '<td>' + (user.email || '') + '</td>' +
          '<td>' + (user.card_serial || '') + '</td>' +
          '<td><button class="action" data-action="delete-user" data-id="' + user.id + '">Remove</button></td>' +
        '</tr>';
      }).join('');
    }

    function renderPermissions(tools) {
      if (!tools.length) {
        toolsBody.innerHTML = '<tr><td colspan="3" class="empty">No permissions yet</td></tr>';
        return;
      }
      toolsBody.innerHTML = tools.map((tool) => {
        const permission = tool.badge_name || tool.id || '';
        const internalId = tool.id ? '<span class="muted">ID: ' + tool.id + '</span>' : '';
        const displayName = tool.name || '';
        return '<tr>' +
          '<td>' + (permission || 'n/a') + internalId + '</td>' +
          '<td>' + (displayName || '') + '</td>' +
          '<td><button class="action" data-action="delete-tool" data-id="' + tool.id + '">Remove</button></td>' +
        '</tr>';
      }).join('');
    }

    function updateAssignmentOptions() {
      const userOptions = currentState.users.map((user) => ({
        value: user.id,
        label: formatUserDisplay(user) || user.id,
      }));
      populateSelect(assignUserSelect, userOptions, { emptyLabel: 'No users' });

      const toolOptions = currentState.tools.map((tool) => ({
        value: tool.id,
        label: formatPermissionDisplay(tool) || tool.id,
      }));
      populateSelect(assignToolSelect, toolOptions, { emptyLabel: 'No permissions' });
    }

    function updateFilters() {
      const userFilters = currentState.users.map((user) => ({
        value: user.id,
        label: user.uuid || user.id,
      }));
      populateSelect(filterUser, userFilters, { includeAll: true, allLabel: 'All people', emptyLabel: 'No people' });

      const toolFilters = currentState.tools.map((tool) => ({
        value: tool.id,
        label: tool.badge_name || tool.id,
      }));
      populateSelect(filterTool, toolFilters, { includeAll: true, allLabel: 'All permissions', emptyLabel: 'No permissions' });
    }

    function renderAssignments() {
      if (!currentState.assignments.length) {
        assignBody.innerHTML = '<tr><td colspan="3" class="empty">No permissions granted</td></tr>';
        return;
      }
      const userFilterValue = filterUser.value;
      const toolFilterValue = filterTool.value;
      const filtered = currentState.assignments.filter(([userId, toolId]) => {
        const userMatches = !userFilterValue || userFilterValue === userId;
        const toolMatches = !toolFilterValue || toolFilterValue === toolId;
        return userMatches && toolMatches;
      });

      if (!filtered.length) {
        assignBody.innerHTML = '<tr><td colspan="3" class="empty">No permissions match the selected filters</td></tr>';
        return;
      }

      assignBody.innerHTML = filtered.map(([userId, toolId]) => {
        const user = currentState.users.find((entry) => entry.id === userId);
        const tool = currentState.tools.find((entry) => entry.id === toolId);
        const userLabel = formatUserDisplay(user) || userId;
        let permissionCell = formatPermissionDisplay(tool) || toolId;
        if (tool && tool.id) {
          permissionCell += '<span class="muted">ID: ' + tool.id + '</span>';
        }
        return '<tr>' +
          '<td>' + userLabel + '</td>' +
          '<td>' + permissionCell + '</td>' +
          '<td><button class="action" data-action="delete-assignment" data-user="' + userId + '" data-tool="' + toolId + '">Remove</button></td>' +
        '</tr>';
      }).join('');
    }

    function updatePermissionOptions() {
      const permissions = currentState.permissions && currentState.permissions.length
        ? currentState.permissions
        : currentState.tools.map((tool) => tool.badge_name).filter(Boolean);
      const uniquePermissions = Array.from(new Set(permissions.map((perm) => (perm || '').toLowerCase()).filter(Boolean)));
      const options = uniquePermissions.map((perm) => {
        const tool = currentState.tools.find((entry) => (entry.badge_name || '').toLowerCase() === perm);
        const labelParts = [];
        if (tool && tool.badge_name) {
          labelParts.push(tool.badge_name);
        } else {
          labelParts.push(perm);
        }
        if (tool && tool.name) {
          labelParts.push(tool.name);
        }
        return { value: perm, label: labelParts.join(' · ') };
      });
      populateSelect(permissionSelect, options, { emptyLabel: 'No permissions' });

      const cardOptions = buildCardOptions();
      populateSelect(permissionCardSelect, cardOptions, { emptyLabel: 'No cards' });
    }

    tabButtons.forEach((button) => {
      button.addEventListener('click', () => {
        activateTab(button.dataset.tab || 'admin');
      });
    });

    document.addEventListener('click', async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const action = target.dataset.action;
      if (!action) {
        return;
      }
      try {
        if (action === 'delete-user') {
          const res = await fetch('/api/users/' + encodeURIComponent(target.dataset.id), { method: 'DELETE' });
          if (!res.ok) {
            throw new Error('Failed to remove user');
          }
          setStatus('Removed user ' + target.dataset.id);
        } else if (action === 'delete-tool') {
          const res = await fetch('/api/tools/' + encodeURIComponent(target.dataset.id), { method: 'DELETE' });
          if (!res.ok) {
            throw new Error('Failed to remove permission');
          }
          setStatus('Removed permission ' + target.dataset.id);
        } else if (action === 'delete-assignment') {
          const res = await fetch('/api/assignments/' + encodeURIComponent(target.dataset.user) + '/' + encodeURIComponent(target.dataset.tool), { method: 'DELETE' });
          if (!res.ok) {
            throw new Error('Failed to revoke permission');
          }
          setStatus('Revoked ' + target.dataset.user + ' → ' + target.dataset.tool);
        }
        await loadState();
      } catch (error) {
        console.error(error);
        setStatus(error.message || 'Unexpected error', true);
      }
    });

    userForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.target;
      const cardSerial = form.card_serial.value.trim();
      if (!cardSerial) {
        setStatus('Card serial is required.', true);
        return;
      }
      const firstName = form.first_name.value.trim();
      const lastName = form.last_name.value.trim();
      const email = form.email.value.trim();
      let uuidValue = form.uuid.value.trim();
      if (!uuidValue) {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
          uuidValue = window.crypto.randomUUID();
        } else {
          uuidValue = 'u_' + Date.now().toString(36);
        }
        form.uuid.value = uuidValue;
      }
      let userId = form.user_id.value.trim();
      if (!userId) {
        userId = uuidValue;
      }
      if (!userId) {
        const slugSource = [firstName, lastName].filter(Boolean).join('_') || email || cardSerial || uuidValue;
        userId = slugify(slugSource) || cardSerial || uuidValue;
      }
      form.user_id.value = userId;
      const payload = {
        user_id: userId,
        card_serial: cardSerial,
        first_name: firstName,
        last_name: lastName,
        uuid: uuidValue,
        email,
      };
      try {
        const res = await fetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || 'Failed to save user');
        }
        setStatus('Saved user ' + (data.uuid || data.id));
        form.reset();
        await loadState();
      } catch (error) {
        console.error(error);
        setStatus(error.message || 'Unexpected error', true);
      }
    });

    toolForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.target;
      const permissionId = form.permission_id.value.trim();
      const displayName = form.name.value.trim();
      if (!permissionId) {
        setStatus('Permission ID is required.', true);
        return;
      }
      const toolIdInput = form.tool_id;
      let toolId = toolIdInput && toolIdInput.value ? toolIdInput.value.trim() : '';
      if (!toolId) {
        const slug = slugify(permissionId);
        toolId = slug ? 'perm.' + slug : permissionId;
        if (toolIdInput) {
          toolIdInput.value = toolId;
        }
      }
      const readerId = toolId;
      const activatorId = toolId;
      const payload = {
        tool_id: toolId,
        device_id: activatorId || toolId,
        reader_device_id: readerId,
        activator_device_id: activatorId,
        badge_name: permissionId,
        name: displayName,
      };
      try {
        const res = await fetch('/api/tools', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || 'Failed to save permission');
        }
        setStatus('Saved permission ' + (data.badge_name || permissionId));
        form.reset();
        await loadState();
      } catch (error) {
        console.error(error);
        setStatus(error.message || 'Unexpected error', true);
      }
    });

    assignForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.target;
      const payload = {
        user_id: form.user_id.value.trim(),
        tool_id: form.tool_id.value.trim(),
      };
      if (!payload.user_id || !payload.tool_id) {
        setStatus('Choose both a person and a permission.', true);
        return;
      }
      try {
        const res = await fetch('/api/assignments', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || 'Failed to grant access');
        }
        const userLabel = assignUserSelect.options[assignUserSelect.selectedIndex]?.textContent || payload.user_id;
        const permissionLabel = assignToolSelect.options[assignToolSelect.selectedIndex]?.textContent || payload.tool_id;
        setStatus('Granted ' + userLabel + ' → ' + permissionLabel);
        await loadState();
      } catch (error) {
        console.error(error);
        setStatus(error.message || 'Unexpected error', true);
      }
    });

    permissionForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const cardSerial = permissionForm.card_id.value.trim();
      const permissionId = permissionForm.permission_id.value.trim();
      if (!cardSerial || !permissionId) {
        setSimStatus('Select a card and permission before sending.', true);
        return;
      }
      const requestContext = buildPermissionRequest(cardSerial, permissionId);
      if (requestContext.requiresUuid && !requestContext.hasUuid) {
        permissionStatusCode.textContent = '-';
        permissionRequest.classList.remove('empty');
        permissionRequest.textContent = 'Cannot build request: selected user needs a UUID for this endpoint.';
        permissionResponse.classList.add('empty');
        permissionResponse.textContent = 'No response yet.';
        setSimStatus('Add a UUID to this user or adjust the permission endpoint template.', true);
        return;
      }
      const url = requestContext.url;
      if (/\\{[^}]+\\}/.test(url)) {
        permissionStatusCode.textContent = '-';
        permissionRequest.classList.remove('empty');
        permissionRequest.textContent = url;
        permissionResponse.classList.add('empty');
        permissionResponse.textContent = 'No response yet.';
        setSimStatus('Permission endpoint template still contains placeholders. Update MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT.', true);
        return;
      }
      permissionRequest.classList.remove('empty');
      permissionRequest.textContent = url;
      permissionResponse.classList.remove('empty');
      permissionResponse.textContent = 'Loading...';
      permissionStatusCode.textContent = '...';
      setSimStatus('Sending permission request...');
      try {
        const res = await fetch(url);
        permissionStatusCode.textContent = String(res.status);
        const rawText = await res.text();
        const parsed = safeParseJson(rawText);
        const display = typeof parsed === 'string' ? parsed : JSON.stringify(parsed, null, 2);
        permissionResponse.textContent = display || 'No response body.';
        if (res.ok) {
          let granted = false;
          if (Array.isArray(parsed)) {
            granted = parsed.some((entry) => String(entry.access).toLowerCase() === 'true');
          }
          setSimStatus(granted ? 'Access granted.' : 'Access denied.', !granted);
        } else {
          const errorMessage = parsed && typeof parsed === 'object' && parsed.error ? parsed.error : 'Permission check failed.';
          setSimStatus(errorMessage, true);
        }
      } catch (error) {
        console.error(error);
        permissionStatusCode.textContent = '-';
        permissionResponse.classList.add('empty');
        permissionResponse.textContent = 'No response yet.';
        setSimStatus('Failed to reach permission endpoint.', true);
      }
    });

    filterUser.addEventListener('change', renderAssignments);
    filterTool.addEventListener('change', renderAssignments);

    clearPre(permissionRequest, 'No request yet.');
    clearPre(permissionResponse, 'No response yet.');
    permissionStatusCode.textContent = '-';

    loadState().catch((error) => {
      console.error(error);
      setStatus('Failed to load state', true);
    });
  </script>
</body>
</html>
"""  # noqa: B950


async def _payload() -> Dict[str, Any]:
    if request.is_json:
        payload = await request.get_json(silent=True)
        return payload or {}
    form = await request.form
    if form:
        return form.to_dict()
    return {}


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _normalize_permission_id(permission_id: str) -> str:
    return (permission_id or "").strip().lower()


def _format_permission_result(
    user: Dict[str, Any], permission: str, access: bool
) -> Dict[str, Any]:
    return {
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "permission": _normalize_permission_id(permission),
        "access": "true" if access else "false",
        "uuid": user.get("uuid", ""),
    }


def _persistence_note() -> str:
    store_path = os.environ.get("CARDSYS_TEST_STORE")
    if store_path:
        return Markup(f"Changes persist to <code>{store_path}</code>.")
    users_path = os.environ.get("CARDSYS_TEST_USERS")
    tools_path = os.environ.get("CARDSYS_TEST_TOOLS")
    assignments_path = os.environ.get("CARDSYS_TEST_ASSIGNMENTS")
    if users_path or tools_path or assignments_path:
        parts = [
            f"users → <code>{users_path}</code>" if users_path else None,
            f"tools → <code>{tools_path}</code>" if tools_path else None,
            (
                f"assignments → <code>{assignments_path}</code>"
                if assignments_path
                else None
            ),
        ]
        readable = ", ".join(filter(None, parts))
        return Markup(f"Changes persist to the legacy fixture files ({readable}).")
    return Markup(
        "No persistence path set — data lives only for this process. "
        "Set <code>CARDSYS_TEST_STORE</code> or the legacy <code>CARDSYS_TEST_*</code>"
        " variables to save changes."
    )


@app.get("/")
async def index() -> str:
    """Render the Maker Access Control UI."""
    return await render_template_string(
        INDEX_HTML,
        persistence_note=_persistence_note(),
        permission_endpoint_template=CONFIG.PERMISSION_ENDPOINT_TEMPLATE,
    )


@app.get("/api/state")
async def api_state() -> Response:
    """Return the current provider state for the UI."""
    provider: AccessProvider = get_provider()
    state: Dict[str, Any] = dict(provider.as_state())
    state["meta"] = {
        "store_path": os.environ.get("CARDSYS_TEST_STORE"),
        "users_path": os.environ.get("CARDSYS_TEST_USERS"),
        "tools_path": os.environ.get("CARDSYS_TEST_TOOLS"),
        "assignments_path": os.environ.get("CARDSYS_TEST_ASSIGNMENTS"),
    }
    state["permissions"] = provider.list_permissions()
    return jsonify(state)


@app.post("/api/users")
async def api_users_create() -> Response:
    """Create or update a user record in the provider store."""
    data = await _payload()
    user_id = (data.get("user_id") or data.get("id") or "").strip()
    card_serial = (data.get("card_serial") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    user_uuid = (data.get("uuid") or data.get("user_uuid") or "").strip()
    email = (data.get("email") or "").strip()

    if not card_serial:
        response = jsonify({"error": "card_serial is required"})
        response.status_code = HTTPStatus.BAD_REQUEST
        return response

    if not user_uuid:
        user_uuid = str(uuid.uuid4())

    if not user_id:
        user_id = user_uuid

    provider: AccessProvider = get_provider()
    provider.upsert_person(
        user_id,
        card_serial,
        first_name=first_name or None,
        last_name=last_name or None,
        user_uuid=user_uuid or None,
        email=email or None,
    )
    person = provider.get_person(user_id) or {
        "id": user_id,
        "card_serial": card_serial,
        "first_name": first_name,
        "last_name": last_name,
        "uuid": user_uuid,
        "email": email,
    }
    response = jsonify(person)
    response.status_code = HTTPStatus.OK
    return response


@app.delete("/api/users/<user_id>")
async def api_users_delete(user_id: str) -> Response:
    """Delete a user from the provider store."""
    provider: AccessProvider = get_provider()
    provider.delete_person(user_id)
    return Response("", status=HTTPStatus.NO_CONTENT)


@app.post("/api/tools")
async def api_tools_create() -> Response:
    """Create or update a tool/permission definition."""
    data = await _payload()
    permission_id = (
        data.get("permission_id")
        or data.get("badge_name")
        or data.get("permission")
        or ""
    ).strip()
    tool_id = (data.get("tool_id") or data.get("id") or "").strip()
    reader_device_id = (
        data.get("reader_device_id")
        or data.get("reader")
        or data.get("reader_device")
        or data.get("device_id")
        or ""
    ).strip()
    activator_device_id = (
        data.get("activator_device_id")
        or data.get("activator")
        or data.get("device_id")
        or ""
    ).strip()
    name = (data.get("name") or "").strip()

    if not permission_id and not tool_id:
        response = jsonify({"error": "permission_id or tool_id is required"})
        response.status_code = HTTPStatus.BAD_REQUEST
        return response

    if not tool_id:
        base = permission_id or name or f"perm_{uuid.uuid4().hex[:8]}"
        slug = _slugify(base)
        tool_id = f"perm.{slug}" if slug else base

    if not permission_id:
        permission_id = tool_id

    if not reader_device_id:
        reader_device_id = tool_id

    if not activator_device_id:
        activator_device_id = reader_device_id

    device_id = activator_device_id or reader_device_id or tool_id

    provider: AccessProvider = get_provider()
    provider.upsert_tool(
        tool_id,
        device_id,
        name or None,
        reader_device_id=reader_device_id or None,
        activator_device_id=activator_device_id or None,
        badge_name=permission_id or None,
    )
    tool = provider.get_tool(tool_id) or {
        "id": tool_id,
        "device_id": device_id,
        "reader_device_id": reader_device_id,
        "activator_device_id": activator_device_id,
        "badge_name": permission_id,
        "name": name,
    }
    response = jsonify(tool)
    response.status_code = HTTPStatus.OK
    return response


@app.delete("/api/tools/<tool_id>")
async def api_tools_delete(tool_id: str) -> Response:
    """Delete a tool or permission definition."""
    provider: AccessProvider = get_provider()
    provider.delete_tool(tool_id)
    return Response("", status=HTTPStatus.NO_CONTENT)


@app.post("/api/assignments")
async def api_assignments_create() -> Response:
    """Grant a permission to a user."""
    data = await _payload()
    user_id = (data.get("user_id") or "").strip()
    tool_id = (data.get("tool_id") or "").strip()
    if not user_id or not tool_id:
        response = jsonify({"error": "user_id and tool_id are required"})
        response.status_code = HTTPStatus.BAD_REQUEST
        return response

    provider: AccessProvider = get_provider()
    if not provider.get_person(user_id):
        response = jsonify({"error": f"User {user_id!r} does not exist"})
        response.status_code = HTTPStatus.NOT_FOUND
        return response
    if not provider.get_tool(tool_id):
        response = jsonify({"error": f"Tool {tool_id!r} does not exist"})
        response.status_code = HTTPStatus.NOT_FOUND
        return response

    provider.grant(user_id, tool_id)
    response = jsonify({"user_id": user_id, "tool_id": tool_id})
    response.status_code = HTTPStatus.OK
    return response


@app.delete("/api/assignments/<user_id>/<tool_id>")
async def api_assignments_delete(user_id: str, tool_id: str) -> Response:
    """Revoke a permission assignment."""
    provider: AccessProvider = get_provider()
    provider.delete_assignment(user_id, tool_id)
    return Response("", status=HTTPStatus.NO_CONTENT)


def _resolve_permission_and_user(
    *,
    provider: AccessProvider,
    user: Dict[str, Any] | None,
    permission_id: str,
) -> tuple[
    Dict[str, Any] | None,
    Dict[str, Any] | None,
    Dict[str, Any] | None,
    HTTPStatus | None,
]:
    """Validate user and permission, returning useful context."""
    if not user:
        return None, None, {"error": "No matching user found."}, HTTPStatus.NOT_FOUND
    tool = provider.find_tool_by_badge(permission_id)
    if not tool:
        return None, None, {"error": "Invalid permission ID."}, HTTPStatus.BAD_REQUEST
    return user, tool, None, None


@app.post("/api/simulator/permission")
async def api_simulator_permission() -> Response:
    """Simulate the Drupal permission endpoint using the local provider."""
    payload = await request.get_json(force=True)
    card_id = (payload or {}).get("card_id", "").strip()
    permission_id = (payload or {}).get("permission_id", "").strip()

    request_url = f"/api/v0/serial/{card_id}/permission/{permission_id}"
    provider: AccessProvider = get_provider()

    if not card_id or not permission_id:
        body = {"error": "card_id and permission_id are required"}
        return (
            jsonify(
                {
                    "request": {"method": "GET", "url": request_url},
                    "response": {"status": HTTPStatus.BAD_REQUEST, "body": body},
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    tool = provider.find_tool_by_badge(permission_id)
    if not tool:
        body = {"error": f"permission '{permission_id}' not found"}
        return (
            jsonify(
                {
                    "request": {"method": "GET", "url": request_url},
                    "response": {"status": HTTPStatus.NOT_FOUND, "body": body},
                }
            ),
            HTTPStatus.NOT_FOUND,
        )

    device_id = tool.get("device_id") or tool.get("activator_device_id") or ""
    has_access = provider.check_access(card_id, device_id)

    if has_access:
        status = HTTPStatus.OK
        body = [{"access": "true", "permission": permission_id}]
    else:
        status = HTTPStatus.FORBIDDEN
        body = {"error": "permission denied"}

    return (
        jsonify(
            {
                "request": {"method": "GET", "url": request_url},
                "response": {"status": status, "body": body},
            }
        ),
        status,
    )


@app.get("/api/v0/serial/<card_serial>/user")
async def api_user_by_serial(card_serial: str) -> Response:
    """Return the Maker provider user with the given card serial."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_card(card_serial)
    if not user:
        response = jsonify({"error": "User not found for serial."})
        response.status_code = HTTPStatus.NOT_FOUND
        return response
    payload = {
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "uuid": user.get("uuid", ""),
        "card_serial": user.get("card_serial", ""),
        "access": "Active",
    }
    response = jsonify(payload)
    response.status_code = HTTPStatus.OK
    return response


@app.get("/api/v0/uuid/<user_uuid>/user")
async def api_user_by_uuid(user_uuid: str) -> Response:
    """Return the Maker provider user with the given UUID."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_uuid(user_uuid)
    if not user:
        response = jsonify({"error": "User not found for uuid."})
        response.status_code = HTTPStatus.NOT_FOUND
        return response
    payload = {
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "uuid": user.get("uuid", ""),
        "card_serial": user.get("card_serial", ""),
        "access": "Active",
    }
    response = jsonify(payload)
    response.status_code = HTTPStatus.OK
    return response


def _permission_response(
    user: Dict[str, Any], permission_id: str, granted: bool
) -> Response:
    result = [_format_permission_result(user, permission_id, granted)]
    status = HTTPStatus.OK if granted else HTTPStatus.FORBIDDEN
    if granted:
        response = jsonify(result)
    else:
        message = "User does not have the specified permission."
        response = jsonify({"error": message})
    response.status_code = status
    return response


@app.get("/api/v0/serial/<card_serial>/permission/<permission_id>")
async def api_permission_by_serial(card_serial: str, permission_id: str) -> Response:
    """Return permission info for a card serial."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_card(card_serial)
    person, _tool, error_body, error_status = _resolve_permission_and_user(
        provider=provider,
        user=user,
        permission_id=permission_id,
    )
    if person is None:
        if error_body is None or error_status is None:
            fallback = jsonify({"error": "Permission context unavailable."})
            fallback.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return fallback
        response = jsonify(error_body)
        response.status_code = int(error_status)
        return response
    granted = provider.has_permission(person["id"], permission_id)
    if granted:
        return _permission_response(person, permission_id, True)
    return _permission_response(person, permission_id, False)


@app.get("/api/v0/uuid/<user_uuid>/permission/<permission_id>")
async def api_permission_by_uuid(user_uuid: str, permission_id: str) -> Response:
    """Return permission info for a user UUID."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_uuid(user_uuid)
    person, _tool, error_body, error_status = _resolve_permission_and_user(
        provider=provider,
        user=user,
        permission_id=permission_id,
    )
    if person is None:
        if error_body is None or error_status is None:
            fallback = jsonify({"error": "Permission context unavailable."})
            fallback.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return fallback
        response = jsonify(error_body)
        response.status_code = int(error_status)
        return response
    granted = provider.has_permission(person["id"], permission_id)
    if granted:
        return _permission_response(person, permission_id, True)
    return _permission_response(person, permission_id, False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)  # noqa: S104
