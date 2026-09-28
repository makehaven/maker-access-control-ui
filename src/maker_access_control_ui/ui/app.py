# noqa: D101,D102,D103
"""Maker Access Control UI application."""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from urllib.parse import quote
from http import HTTPStatus
from typing import Any
from typing import Dict
from urllib.error import HTTPError
from urllib.error import URLError

from quart import Quart
from quart import Response
from quart import jsonify
from quart import render_template_string
from quart import request
from markupsafe import Markup

from maker_access_control_ui.access.provider import AccessProvider
from maker_access_control_ui.access.provider import get_provider
from maker_access_control_ui.config import CONFIG
from maker_access_control_ui import logforward as logforward_service
from maker_access_control_ui import proxy as proxy_service
from maker_access_control_ui import sync as sync_service


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
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin-top: 0.75rem; }
    .stat { background: #f8f9fa; border-radius: 8px; padding: 0.75rem 1rem; border: 1px solid #e3e6eb; }
    .stat .label { font-size: 0.85rem; color: #5c677d; }
    .stat .value { font-size: 1.75rem; font-weight: 600; margin-top: 0.15rem; color: #0b7285; }
    .tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
    .tabs button { padding: 0.45rem 1rem; border: none; border-radius: 999px; background: #dee2e6; color: #1f2933; cursor: pointer; font-weight: 600; }
    .tabs button.active { background: #0b7285; color: #fff; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .grid { display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }
    section { background: #fff; border-radius: 8px; padding: 1rem 1.25rem 1.25rem; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
    form { display: grid; gap: 0.5rem; margin-bottom: 1rem; }
    form .row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    input, select { flex: 1 1 48%; padding: 0.45rem 0.5rem; border: 1px solid #ccc; border-radius: 4px; }
    label { width: 100%; font-size: 0.85rem; color: #555; }
    form button { justify-self: flex-start; padding: 0.45rem 0.9rem; background: #0b7285; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { border-bottom: 1px solid #e6e6e6; padding: 0.45rem 0.25rem; text-align: left; vertical-align: top; }
    tr:last-child td { border-bottom: none; }
    tr.no-assignment { background: #fff4e6; }
    tr.no-assignment td { border-bottom-color: #f8d7b6; }
    .badge { display: inline-block; padding: 0.1rem 0.4rem; font-size: 0.75rem; border-radius: 999px; background: #ffe8cc; color: #ad5700; margin-left: 0.35rem; }
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
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <h1>Maker Access Control</h1>
  <div class="intro">
    <p><strong>What this is:</strong> a lightweight admin surface that replaces Drupal for test environments or simple deployments. It stores data in JSON so you can iterate quickly.</p>
    <p><strong>Persistence:</strong> {{ persistence_note }}</p>
    <div class="stats">
      <div class="stat">
        <div class="label">People</div>
        <div class="value" id="stat-users">0</div>
      </div>
      <div class="stat">
        <div class="label">Assignments</div>
        <div class="value" id="stat-assignments">0</div>
      </div>
      <div class="stat">
        <div class="label">Permissions defined</div>
        <div class="value" id="stat-permissions">0</div>
      </div>
    </div>
    <p><strong>Workflow:</strong> 1) add people &amp; assign card serials, 2) register permissions by badge text (IDs/devices fill in automatically), 3) grant access, 4) use the simulator to inspect API responses or swipe behavior.</p>
    <p><strong>Need data from Drupal?</strong> Visit the <a href="/sync">Sync from Drupal</a> page to pull the latest fallback export. Need to manage the badge catalog? Use the <a href="/permissions">Permissions page</a>.</p>
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
      <h2>Permission Assignments</h2>
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
          <label>Permission
            <select name="permission_id" id="permission-select" required></select>
          </label>
        </div>
        <div class="row">
          <label>Card serial
            <select name="card_id" id="permission-card" required></select>
          </label>
          <label>Email
            <select name="email" id="permission-email"></select>
          </label>
        </div>
        <button type="submit">Send Request</button>
      </form>
      <div class="grid">
        <div>
          <span class="block-label">Serial request URL</span>
          <pre id="permission-request-card" class="empty">No request yet.</pre>
        </div>
        <div>
          <span class="block-label">Email request URL</span>
          <pre id="permission-request-email" class="empty">No request yet.</pre>
        </div>
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
    const assignBody = document.getElementById('assign-body');
    const assignUserSelect = document.getElementById('assign-user');
    const assignToolSelect = document.getElementById('assign-tool');
    const filterUser = document.getElementById('filter-user');
    const filterTool = document.getElementById('filter-tool');
    const permissionCardSelect = document.getElementById('permission-card');
    const permissionEmailSelect = document.getElementById('permission-email');
    const permissionModeSelect = document.getElementById('permission-mode');
    const permissionSelect = document.getElementById('permission-select');
    const permissionRequestCard = document.getElementById('permission-request-card');
    const permissionRequestEmail = document.getElementById('permission-request-email');
    const permissionResponse = document.getElementById('permission-response');
    const permissionStatusCode = document.getElementById('permission-status-code');
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabPanels = document.querySelectorAll('.tab-panel');
    const userForm = document.getElementById('user-form');
    const assignForm = document.getElementById('assign-form');
    const permissionForm = document.getElementById('permission-form');

    const statUsers = document.getElementById('stat-users');
    const statAssignments = document.getElementById('stat-assignments');
    const statPermissions = document.getElementById('stat-permissions');

    let currentState = { users: [], tools: [], assignments: [], permissions: [], meta: {} };
    const permissionTemplateDefault = '/api/v0/serial/{card_serial}/permission/{permission_id}';
    const permissionEndpointTemplateRaw = {{ permission_endpoint_template | tojson }};
    const permissionEndpointTemplate = (permissionEndpointTemplateRaw || permissionTemplateDefault).trim() || permissionTemplateDefault;
    const permissionEmailTemplateDefault = '/api/v0/email/{email}/permission/{permission_id}';
    const permissionEndpointEmailTemplateRaw = {{ permission_endpoint_email_template | tojson }};
    const permissionEmailTemplate = (permissionEndpointEmailTemplateRaw || permissionEmailTemplateDefault).trim() || permissionEmailTemplateDefault;

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

    function setPre(element, text) {
      if (!element) {
        return;
      }
      element.classList.remove('empty');
      element.textContent = text;
    }

    function updateStats() {
      if (statUsers) {
        statUsers.textContent = String(currentState.users.length || 0);
      }
      if (statAssignments) {
        statAssignments.textContent = String(currentState.assignments.length || 0);
      }
      if (statPermissions) {
        const uniquePermissions = new Set(
          (currentState.tools || []).map((tool) => (tool.badge_name || tool.id || '').toLowerCase()).filter(Boolean)
        );
        statPermissions.textContent = String(uniquePermissions.size);
      }
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

    function buildEmailOptions() {
      return currentState.users
        .map((user) => {
          if (!user.email) {
            return null;
          }
          const parts = [user.email];
          const name = [user.first_name, user.last_name].filter(Boolean).join(' ');
          if (name) {
            parts.push(name);
          }
          if (user.card_serial) {
            parts.push(user.card_serial);
          }
          return { value: user.email, label: parts.join(' · ') };
        })
        .filter(Boolean);
    }

    function findUserByCard(cardSerial) {
      const normalizedCard = (cardSerial || '').toLowerCase();
      return currentState.users.find(
        (user) => (user.card_serial || '').toLowerCase() === normalizedCard,
      );
    }

    function findUserByEmail(email) {
      const normalizedEmail = (email || '').toLowerCase();
      return currentState.users.find(
        (user) => (user.email || '').toLowerCase() === normalizedEmail,
      );
    }

    function getPermissionMode() {
      return permissionModeSelect ? (permissionModeSelect.value || 'card') : 'card';
    }

    function togglePermissionSources() {
      const mode = getPermissionMode();
      const cardContainer = document.querySelector('[data-source="card"]');
      const emailContainer = document.querySelector('[data-source="email"]');
      if (cardContainer) {
        cardContainer.classList.toggle('hidden', mode !== 'card');
      }
      if (emailContainer) {
        emailContainer.classList.toggle('hidden', mode !== 'email');
      }
      if (permissionCardSelect) {
        permissionCardSelect.disabled = mode !== 'card';
        permissionCardSelect.required = mode === 'card';
      }
      if (permissionEmailSelect) {
        permissionEmailSelect.disabled = mode !== 'email';
        permissionEmailSelect.required = mode === 'email';
      }
    }

    function getRequestPreviewElement(mode) {
      return mode === 'email' ? permissionRequestEmail : permissionRequestCard;
    }

    function updateRequestPreview(mode, context) {
      const target = getRequestPreviewElement(mode);
      if (!target) {
        return;
      }
      if (!context) {
        clearPre(target, 'No request yet.');
        return;
      }
      setPre(target, context.url);
    }

    function buildPermissionRequest({ mode, cardSerial, email, permissionId }) {
      const selectedUser = mode === 'email'
        ? findUserByEmail(email)
        : findUserByCard(cardSerial);
      const template = mode === 'email' ? permissionEmailTemplate : permissionEndpointTemplate;
      const resolvedCard = cardSerial || (selectedUser && selectedUser.card_serial) || '';
      const resolvedEmail = email || (selectedUser && selectedUser.email) || '';
      const replacements = [
        ['{card_serial}', encodeURIComponent(resolvedCard)],
        ['{card_id}', encodeURIComponent(resolvedCard)],
        ['{email}', encodeURIComponent(resolvedEmail)],
        ['{permission_id}', encodeURIComponent(permissionId)],
        ['{permission}', encodeURIComponent(permissionId)],
      ];
      let uuidValue = '';
      if (selectedUser && selectedUser.uuid) {
        uuidValue = encodeURIComponent(selectedUser.uuid);
      }
      replacements.push(['{uuid}', uuidValue]);

      let url = template;
      replacements.forEach(([needle, value]) => {
        if (!needle) {
          return;
        }
        url = url.split(needle).join(value);
      });

      return {
        url,
        requiresUuid: template.includes('{uuid}'),
        hasUuid: Boolean(uuidValue),
        selectedUser,
        mode,
        templateKey: mode === 'email'
          ? 'MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL'
          : 'MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT',
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
      updateAssignmentOptions();
      updateFilters();
      renderAssignments();
      updatePermissionOptions();
      updateStats();
    }

    function renderUsers(users) {
      if (!users.length) {
        usersBody.innerHTML = '<tr><td colspan="6" class="empty">No users yet</td></tr>';
        return;
      }
      usersBody.innerHTML = users.map((user) => {
        const hasAssignments = currentState.assignments.some(([userId]) => userId === user.id);
        const rowClass = hasAssignments ? '' : ' class="no-assignment"';
        const uuid = user.uuid || '';
        const badge = hasAssignments ? '' : '<span class="badge">No access</span>';
        return '<tr' + rowClass + '>' +
          '<td>' + (uuid || user.id || '') + badge + '</td>' +
          '<td>' + (user.first_name || '') + '</td>' +
          '<td>' + (user.last_name || '') + '</td>' +
          '<td>' + (user.email || '') + '</td>' +
          '<td>' + (user.card_serial || '') + '</td>' +
          '<td><button class="action" data-action="delete-user" data-id="' + user.id + '">Remove</button></td>' +
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
      if (permissionCardSelect) {
        populateSelect(permissionCardSelect, cardOptions, { emptyLabel: 'No cards' });
      }
      const emailOptions = buildEmailOptions();
      if (permissionEmailSelect) {
        populateSelect(permissionEmailSelect, emailOptions, { emptyLabel: 'No emails' });
      }
      togglePermissionSources();
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
      const mode = getPermissionMode();
      const cardSerial = permissionCardSelect ? permissionCardSelect.value.trim() : '';
      const emailValue = permissionEmailSelect ? permissionEmailSelect.value.trim() : '';
      const permissionId = permissionSelect ? permissionSelect.value.trim() : '';
      if (!permissionId) {
        setSimStatus('Select a permission before sending.', true);
        return;
      }
      if (mode === 'card' && !cardSerial) {
        setSimStatus('Select a card serial before sending.', true);
        return;
      }
      if (mode === 'email' && !emailValue) {
        setSimStatus('Select an email before sending.', true);
        return;
      }
      const requestContext = buildPermissionRequest({
        mode,
        cardSerial,
        email: emailValue,
        permissionId,
      });
      const activePreview = getRequestPreviewElement(mode);
      const selectedUser = requestContext.selectedUser;
      const resolvedCard = cardSerial || (selectedUser && selectedUser.card_serial) || '';
      const resolvedEmail = emailValue || (selectedUser && selectedUser.email) || '';
      if (requestContext.requiresUuid && !requestContext.hasUuid) {
        permissionStatusCode.textContent = '-';
        setPre(activePreview, 'Cannot build request: selected user needs a UUID for this endpoint.');
        permissionResponse.classList.add('empty');
        permissionResponse.textContent = 'No response yet.';
        setSimStatus('Add a UUID to this user or adjust the permission endpoint template.', true);
        return;
      }
      const url = requestContext.url;
      if (/\\{[^}]+\\}/.test(url)) {
        permissionStatusCode.textContent = '-';
        setPre(activePreview, url);
        permissionResponse.classList.add('empty');
        permissionResponse.textContent = 'No response yet.';
        const variables =
          requestContext.templateKey === 'MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL'
            ? 'MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL'
            : 'MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT';
        setSimStatus('Permission endpoint template still contains placeholders. Update ' + variables + '.', true);
        return;
      }
      const cardContext =
        resolvedCard && mode === 'card'
          ? requestContext
          : resolvedCard
            ? buildPermissionRequest({ mode: 'card', cardSerial: resolvedCard, permissionId })
            : null;
      const emailContext =
        resolvedEmail && mode === 'email'
          ? requestContext
          : resolvedEmail
            ? buildPermissionRequest({ mode: 'email', email: resolvedEmail, permissionId })
            : null;
      updateRequestPreview('card', cardContext);
      updateRequestPreview('email', emailContext);

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

    clearPre(permissionRequestCard, 'No request yet.');
    clearPre(permissionRequestEmail, 'No request yet.');
    clearPre(permissionResponse, 'No response yet.');
    permissionStatusCode.textContent = '-';

    togglePermissionSources();

    loadState().catch((error) => {
      console.error(error);
      setStatus('Failed to load state', true);
    });
  </script>
</body>
</html>
"""  # noqa: B950

SYNC_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Sync from Drupal · Maker Access Control</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 1.5rem; color: #222; }
    a { color: #0b7285; }
    .card { background: #fff; border-radius: 8px; padding: 1.25rem 1.5rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); max-width: 800px; margin: 0 auto 1.5rem; }
    h1 { margin-top: 0; }
    form { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    form label { display: flex; flex-direction: column; font-size: 0.9rem; color: #555; }
    input[type="url"], input[type="password"], input[type="text"] { padding: 0.5rem 0.6rem; border: 1px solid #ccc; border-radius: 4px; margin-top: 0.35rem; width: 100%; }
    .remember { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: #555; grid-column: 1 / -1; }
    button { justify-self: flex-start; padding: 0.5rem 1rem; background: #0b7285; color: #fff; border: none; border-radius: 4px; cursor: pointer; grid-column: 1 / -1; }
    .status { min-height: 1.2em; margin-top: 0.5rem; font-weight: 600; }
    .status.error { color: #c92a2a; }
    .status.success { color: #2f9e44; }
    .helper-text { color: #4b5563; font-size: 0.9rem; margin-bottom: 1rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Sync from Drupal</h1>
    <p class="helper-text">Download the cached fallback export from your Drupal site and load it into this lightweight UI. Provide the full URL to <code>/api/v0/access-control/fallback-store</code> plus the shared download code configured in Drupal.</p>
    <p class="helper-text">Need to manage users and permissions instead? <a href="/">Return to the admin UI</a>.</p>
    <form id="sync-form">
      <label>Fallback export URL
        <input type="url" id="sync-url" name="source_url" placeholder="https://makehaven-website.lndo.site/api/v0/access-control/fallback-store" required />
      </label>
      <label>Download code
        <input type="password" id="sync-code" name="download_code" placeholder="Shared download code" autocomplete="off" />
      </label>
      <label class="remember">
        <input type="checkbox" id="sync-remember" />
        Remember download code in this browser
      </label>
      <button type="submit">Download latest data</button>
    </form>
    <p class="status" id="sync-status"></p>
    <p class="helper-text">Local persistence: {{ persistence_note }}</p>
  </div>
  <script>
    const syncForm = document.getElementById('sync-form');
    const syncUrlInput = document.getElementById('sync-url');
    const syncCodeInput = document.getElementById('sync-code');
    const syncRememberInput = document.getElementById('sync-remember');
    const syncStatusEl = document.getElementById('sync-status');
    const syncDefaults = {
      url: {{ fallback_source_url | tojson }},
      code: {{ fallback_download_code | tojson }},
    };
    const syncStorageKey = 'makerAccessControl.import';

    function setSyncStatus(message, isError = false) {
      if (!syncStatusEl) {
        return;
      }
      syncStatusEl.textContent = message || '';
      syncStatusEl.classList.remove('error', 'success');
      if (!message) {
        return;
      }
      syncStatusEl.classList.add(isError ? 'error' : 'success');
    }

    function readSyncSettings() {
      if (!window.localStorage) {
        return null;
      }
      try {
        const raw = localStorage.getItem(syncStorageKey);
        if (!raw) {
          return null;
        }
        return JSON.parse(raw);
      } catch (error) {
        console.warn('Failed to read sync settings', error);
        return null;
      }
    }

    function applySyncDefaults() {
      if (!syncForm) {
        return;
      }
      const stored = readSyncSettings();
      const urlValue = (stored && stored.url) || syncDefaults.url || '';
      let codeValue = '';
      if (stored && stored.remember && stored.code) {
        codeValue = stored.code;
      } else if (!stored && syncDefaults.code) {
        codeValue = syncDefaults.code;
      }
      syncUrlInput.value = urlValue;
      syncCodeInput.value = codeValue;
      syncRememberInput.checked = Boolean(stored && stored.remember && stored.code);
    }

    function persistSyncSettings(url, code, remember) {
      if (!window.localStorage) {
        return;
      }
      const payload = { url: url || '' };
      if (remember && code) {
        payload.code = code;
        payload.remember = true;
      } else if (remember) {
        payload.remember = true;
      }
      try {
        localStorage.setItem(syncStorageKey, JSON.stringify(payload));
      } catch (error) {
        console.warn('Failed to persist sync settings', error);
      }
    }

    if (syncForm) {
      applySyncDefaults();
      syncForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const urlValue = syncUrlInput.value.trim();
        const codeValue = syncCodeInput.value.trim();
        const rememberCode = syncRememberInput.checked;
        if (!urlValue) {
          setSyncStatus('Fallback export URL is required.', true);
          return;
        }
        const submitButton = syncForm.querySelector('button[type="submit"]');
        if (submitButton) {
          submitButton.disabled = true;
        }
        setSyncStatus('Downloading fallback store...');
        try {
          const res = await fetch('/api/store/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: urlValue, code: codeValue }),
          });
          let data = {};
          try {
            data = await res.json();
          } catch (error) {
            data = {};
          }
          if (!res.ok) {
            throw new Error(data.error || 'Failed to import fallback store.');
          }
          const peopleCount = typeof data.users === 'number' ? data.users : 0;
          const toolCount = typeof data.tools === 'number' ? data.tools : 0;
          const assignmentCount = typeof data.assignments === 'number' ? data.assignments : 0;
          setSyncStatus('Imported ' + peopleCount + ' people, ' + toolCount + ' permissions, ' + assignmentCount + ' assignments.');
          persistSyncSettings(urlValue, codeValue, rememberCode);
        } catch (error) {
          console.error(error);
          setSyncStatus(error.message || 'Failed to import fallback store.', true);
        } finally {
          if (submitButton) {
            submitButton.disabled = false;
          }
        }
      });
    }
  </script>
</body>
</html>
"""

PERMISSIONS_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Permissions · Maker Access Control</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 1.5rem; color: #222; }
    a { color: #0b7285; }
    .card { background: #fff; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); max-width: 960px; margin: 0 auto; }
    h1 { margin-top: 0; }
    form { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); margin-bottom: 1.25rem; }
    form label { display: flex; flex-direction: column; font-size: 0.9rem; color: #555; }
    input[type="text"] { padding: 0.5rem 0.6rem; border: 1px solid #ccc; border-radius: 4px; margin-top: 0.35rem; width: 100%; }
    button { justify-self: flex-start; padding: 0.5rem 1rem; background: #0b7285; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    th, td { border-bottom: 1px solid #e6e6e6; padding: 0.45rem 0.25rem; text-align: left; vertical-align: top; }
    tr:last-child td { border-bottom: none; }
    button.action { background: transparent; color: #b00020; border: none; cursor: pointer; padding: 0; font-size: 0.85rem; }
    button.action:hover { text-decoration: underline; }
    .status { min-height: 1.2em; margin-bottom: 1rem; font-weight: 600; }
    .status.error { color: #c92a2a; }
    .status.success { color: #2f9e44; }
    .helper-text { color: #4b5563; font-size: 0.9rem; margin-bottom: 1rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Permission Catalog</h1>
    <p class="helper-text">Define the badge or permission IDs exposed to access points. These values must match Drupal's <code>field_badge_text_id</code>. <a href="/">Back to the admin UI</a>.</p>
    <form id="perm-form">
      <label>Permission ID (badge text ID)
        <input name="permission_id" id="perm-id" placeholder="laser" required />
      </label>
      <label>Display name
        <input name="name" id="perm-name" placeholder="Laser Cutter" />
      </label>
      <button type="submit">Add or Update Permission</button>
    </form>
    <p class="status" id="perm-status"></p>
    <table>
      <thead>
        <tr><th>Permission ID</th><th>Display Name</th><th>Internal ID</th><th></th></tr>
      </thead>
      <tbody id="perm-body">
        <tr><td colspan="4" class="empty">Loading…</td></tr>
      </tbody>
    </table>
  </div>
  <script>
    const permForm = document.getElementById('perm-form');
    const permBody = document.getElementById('perm-body');
    const permStatus = document.getElementById('perm-status');
    const permIdInput = document.getElementById('perm-id');
    const permNameInput = document.getElementById('perm-name');

    function setPermStatus(message, isError = false) {
      permStatus.textContent = message || '';
      permStatus.classList.remove('error', 'success');
      if (!message) {
        return;
      }
      permStatus.classList.add(isError ? 'error' : 'success');
    }

    async function loadPermissions() {
      const res = await fetch('/api/state');
      if (!res.ok) {
        throw new Error('Unable to fetch permissions');
      }
      const data = await res.json();
      renderPermissions(data.tools || []);
    }

    function renderPermissions(tools) {
      if (!tools.length) {
        permBody.innerHTML = '<tr><td colspan="4" class="empty">No permissions defined yet.</td></tr>';
        return;
      }
      permBody.innerHTML = tools.map((tool) => {
        const permission = tool.badge_name || tool.id || '';
        const name = tool.name || '';
        return '<tr>' +
          '<td>' + (permission || 'n/a') + '</td>' +
          '<td>' + (name || '') + '</td>' +
          '<td>' + (tool.id || '') + '</td>' +
          '<td><button class="action" data-action="delete" data-id="' + tool.id + '">Remove</button></td>' +
        '</tr>';
      }).join('');
    }

    permBody.addEventListener('click', async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      if (target.dataset.action !== 'delete') {
        return;
      }
      const toolId = target.dataset.id;
      if (!toolId) {
        return;
      }
      try {
        const res = await fetch('/api/tools/' + encodeURIComponent(toolId), { method: 'DELETE' });
        if (!res.ok) {
          throw new Error('Failed to remove permission');
        }
        setPermStatus('Removed permission ' + toolId);
        await loadPermissions();
      } catch (error) {
        console.error(error);
        setPermStatus(error.message || 'Failed to remove permission.', true);
      }
    });

    permForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const permissionId = permIdInput.value.trim();
      const name = permNameInput.value.trim();
      if (!permissionId) {
        setPermStatus('Permission ID is required.', true);
        return;
      }
      try {
        const res = await fetch('/api/tools', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ permission_id: permissionId, name }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || 'Failed to save permission');
        }
        setPermStatus('Saved permission ' + (data.badge_name || data.id || permissionId));
        permForm.reset();
        await loadPermissions();
      } catch (error) {
        console.error(error);
        setPermStatus(error.message || 'Failed to save permission.', true);
      }
    });

    loadPermissions().catch((error) => {
      console.error(error);
      setPermStatus('Failed to load permissions.', true);
    });
  </script>
</body>
</html>
"""


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


async def _fetch_fallback_store(source_url: str, download_code: str) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: _fetch_fallback_store_sync(source_url, download_code)
    )


def _fetch_fallback_store_sync(source_url: str, download_code: str) -> Dict[str, Any]:
    """Download the export for the manual UI path.

    Delegates to :mod:`maker_access_control_ui.sync` so the manual button and
    the unattended loop cannot drift apart in how they build the URL, present
    the shared code, or parse the response.
    """
    payload, _etag = sync_service.fetch_fallback_store_sync(
        source_url, download_code, timeout=CONFIG.SYNC_TIMEOUT_SECONDS
    )
    if payload is sync_service.UNCHANGED:  # pragma: no cover - no ETag sent here
        raise ValueError("Fallback export reported no change without a prior ETag.")
    return payload


def _build_fallback_url(source_url: str, download_code: str) -> str:
    return sync_service.build_fallback_url(source_url, download_code)


def _json_error(message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> Response:
    response = jsonify({"error": message})
    response.status_code = status
    return response


@app.get("/")
async def index() -> str:
    """Render the Maker Access Control UI."""
    return await render_template_string(
        INDEX_HTML,
        persistence_note=_persistence_note(),
        permission_endpoint_template=CONFIG.PERMISSION_ENDPOINT_TEMPLATE,
        permission_endpoint_email_template=CONFIG.PERMISSION_ENDPOINT_EMAIL_TEMPLATE,
        fallback_source_url=CONFIG.FALLBACK_SOURCE_URL,
        fallback_download_code=CONFIG.FALLBACK_DOWNLOAD_CODE,
    )


@app.get("/sync")
async def sync_page() -> str:
    """Render the Drupal sync helper view."""
    return await render_template_string(
        SYNC_HTML,
        persistence_note=_persistence_note(),
        fallback_source_url=CONFIG.FALLBACK_SOURCE_URL,
        fallback_download_code=CONFIG.FALLBACK_DOWNLOAD_CODE,
        permission_endpoint_template=CONFIG.PERMISSION_ENDPOINT_TEMPLATE,
        permission_endpoint_email_template=CONFIG.PERMISSION_ENDPOINT_EMAIL_TEMPLATE,
    )


@app.get("/permissions")
async def permissions_page() -> str:
    """Render the permission catalog editor."""
    return await render_template_string(
        PERMISSIONS_HTML,
        persistence_note=_persistence_note(),
        permission_endpoint_template=CONFIG.PERMISSION_ENDPOINT_TEMPLATE,
        permission_endpoint_email_template=CONFIG.PERMISSION_ENDPOINT_EMAIL_TEMPLATE,
        fallback_source_url=CONFIG.FALLBACK_SOURCE_URL,
        fallback_download_code=CONFIG.FALLBACK_DOWNLOAD_CODE,
    )


@app.get("/health")
async def health() -> Response:
    """Report whether this box is still fit to make access decisions.

    Answers 200 while the store is fresh enough to trust and 503 once it is
    not, so an uptime monitor can page on the failure that matters most: a box
    that is happily answering from data that stopped being refreshed.
    """
    body, status = sync_service.health_report()
    response = jsonify(body)
    response.status_code = status
    return response


@app.post("/api/sync/run")
async def api_sync_run() -> Response:
    """Run one synchronisation immediately, for operators and for tests."""
    data = await _payload()
    force = str(data.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
    result = await sync_service.run_sync_once(force=force)
    response = jsonify(result)
    response.status_code = (
        HTTPStatus.OK
        if result.get("status") in {"ok", "unchanged"}
        else HTTPStatus.BAD_GATEWAY
    )
    return response


@app.post("/api/log-forward/drain")
async def api_log_forward_drain() -> Response:
    """Drain one batch of forwarded decisions immediately."""
    result = await logforward_service.drain_once()
    response = jsonify(result)
    response.status_code = (
        HTTPStatus.OK
        if result.get("status") in {"ok", "empty", "disabled"}
        else HTTPStatus.BAD_GATEWAY
    )
    return response


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


@app.post("/api/store/import")
async def api_store_import() -> Response:
    """Fetch the fallback JSON export from Drupal and load it into the provider."""
    data = await _payload()
    source_url = (
        data.get("url")
        or data.get("source_url")
        or data.get("base_url")
        or CONFIG.FALLBACK_SOURCE_URL
        or ""
    ).strip()
    download_code = (
        data.get("code")
        or data.get("download_code")
        or data.get("fallback_code")
        or CONFIG.FALLBACK_DOWNLOAD_CODE
        or ""
    ).strip()

    if not source_url:
        return _json_error("Fallback export URL is required.", HTTPStatus.BAD_REQUEST)

    try:
        payload = await _fetch_fallback_store(source_url, download_code)
    except HTTPError as error:
        message = f"Remote server returned HTTP {error.code}."
        try:
            detail = error.read().decode("utf-8")  # type: ignore[attr-defined]
            if detail:
                message = f"{message} {detail}"
        except Exception:  # noqa: BLE001
            pass
        return _json_error(message, HTTPStatus.BAD_GATEWAY)
    except URLError as error:
        return _json_error(f"Unable to reach remote host: {error.reason}", HTTPStatus.BAD_GATEWAY)
    except ValueError as error:
        return _json_error(str(error), HTTPStatus.BAD_GATEWAY)
    except Exception as error:  # noqa: BLE001
        logger.exception("Unexpected error downloading fallback export: %s", error)
        return _json_error("Unexpected error downloading fallback export.", HTTPStatus.BAD_GATEWAY)

    provider: AccessProvider = get_provider()
    importer = getattr(provider, "import_store_payload", None)
    if not callable(importer):
        return _json_error(
            "The active access provider does not support remote imports.",
            HTTPStatus.CONFLICT,
        )

    # The same floors the unattended loop enforces: a well-formed but
    # half-empty export must not be allowed to revoke the membership, whether
    # a timer or a person pressed the button.  ``force`` exists for the
    # legitimate small-store cases (a fresh dev site) and says so out loud.
    force = str(data.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not force:
        try:
            sync_service.validate_payload(
                payload,
                len(provider.list_people()),
                min_users=CONFIG.SYNC_MIN_USERS,
                max_shrink_ratio=CONFIG.SYNC_MAX_SHRINK_RATIO,
            )
        except sync_service.PayloadRejected as error:
            return _json_error(
                f"{error} Send \"force\": true to install it anyway.",
                HTTPStatus.CONFLICT,
            )

    try:
        summary = importer(payload)
    except ValueError as error:
        return _json_error(str(error), HTTPStatus.BAD_REQUEST)
    except Exception as error:  # noqa: BLE001
        logger.exception("Unable to import fallback store payload: %s", error)
        return _json_error("Unable to import fallback store payload.", HTTPStatus.INTERNAL_SERVER_ERROR)

    # A hand-loaded store is still a synced store; recording it keeps /health
    # honest instead of reporting an unknown age on a box that was just filled.
    generated_at = payload.get("generated_at")
    sync_service.STATE.source_url = source_url
    sync_service.STATE.record_success(
        summary,
        None,
        generated_at if isinstance(generated_at, str) else None,
        changed=True,
        now=time.time(),
    )
    sync_service.save_state()

    response = jsonify(
        {
            "source_url": source_url,
            "users": summary.get("users", 0),
            "tools": summary.get("tools", 0),
            "assignments": summary.get("assignments", 0),
        }
    )
    response.status_code = HTTPStatus.OK
    return response


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
    email = (payload or {}).get("email", "").strip()
    permission_id = (payload or {}).get("permission_id", "").strip()
    mode = ((payload or {}).get("mode", "card") or "card").strip().lower()
    if mode not in {"card", "email"}:
        body = {"error": "mode must be 'card' or 'email'."}
        return (
            jsonify(
                {
                    "request": {"method": "GET", "url": f"/api/v0/serial/{card_id}/permission/{permission_id}"},
                    "response": {"status": HTTPStatus.BAD_REQUEST, "body": body},
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    identifier = card_id if mode == "card" else email
    request_url = (
        f"/api/v0/serial/{identifier}/permission/{permission_id}"
        if mode == "card"
        else f"/api/v0/email/{identifier}/permission/{permission_id}"
    )
    provider: AccessProvider = get_provider()

    if not identifier or not permission_id:
        missing = "email" if mode == "email" else "card_id"
        body = {"error": f"{missing} and permission_id are required"}
        return (
            jsonify(
                {
                    "request": {"method": "GET", "url": request_url},
                    "response": {"status": HTTPStatus.BAD_REQUEST, "body": body},
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    if mode == "card":
        user = provider.find_user_by_card(identifier)
    else:
        user = provider.find_user_by_email(identifier)

    person, tool, error_body, error_status = _resolve_permission_and_user(
        provider=provider,
        user=user,
        permission_id=permission_id,
    )
    if person is None:
        status = int(error_status or HTTPStatus.BAD_REQUEST)
        body = error_body or {"error": "Permission context unavailable."}
    else:
        has_access = provider.has_permission(person["id"], permission_id)
        if has_access:
            status = HTTPStatus.OK
            body = [_format_permission_result(person, permission_id, True)]
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


@app.route("/user/login", methods=["GET", "POST"])
async def drupal_login_shim() -> Response:
    """Complete Drupal's form-login handshake for cardsystem clients.

    cardsystem's ``DrupalClient.__aenter__`` POSTs credentials to
    ``BADGE_PERMISSION_LOGIN_URL`` and calls ``raise_for_status()`` before it
    will issue any lookup. Without a 200 here the client raises
    ``HTTPStatusError``, ``fetch_user_info`` swallows it and returns ``None``,
    and every badge tap fails closed with "no user found" -- even though the
    lookup endpoints themselves work.

    The box does not authenticate its callers (it is LAN-only, reached from a
    fixed set of devices), so this only has to complete the handshake. Any
    credentials presented are accepted and discarded.
    """
    if request.method == "POST":
        await request.form
    response = jsonify({"status": "ok", "note": "login accepted (box is LAN-only)"})
    response.status_code = HTTPStatus.OK
    return response


_CALLER_LABEL = re.compile(r"[^A-Za-z0-9_.:-]")
LOCAL_BOX_NOTE = "Answered by local box"


def _caller_label(name: str) -> str:
    """Return a caller-supplied ``source``/``method`` label, cleaned for the log."""
    return _CALLER_LABEL.sub("", str(request.args.get(name, "") or ""))[:64]


def _forward_fields(default_method: str, note: str = "") -> Dict[str, str]:
    """Log-forward fields for this request.

    Callers say which device asked (``?source=front_door``) and how
    (``?method=card_reader``), exactly as they do when asking Drupal, and the
    access log shows those. Without them the box falls back to what it knows:
    it answered (``local_authority``) and which lookup was used. Either way the
    note records that the box, not Drupal, made the decision, so reports can
    still tell the two apart.
    """
    return {
        "source": _caller_label("source") or "local_authority",
        "method": _caller_label("method") or default_method,
        "note": f"{LOCAL_BOX_NOTE}. {note}".strip() if note else LOCAL_BOX_NOTE,
    }


def _caller_query() -> str:
    """The caller's ``source``/``method`` as a query string for a proxied lookup."""
    pairs = [(k, _caller_label(k)) for k in ("source", "method")]
    kept = [f"{k}={quote(v)}" for k, v in pairs if v]
    return ("?" + "&".join(kept)) if kept else ""


async def _proxied(path: str, reason: str) -> Response | None:
    """Return Drupal's answer for ``path``, or ``None`` to keep the local one."""
    if "/permission/" in path:
        path += _caller_query()
    result = await proxy_service.maybe_proxy(path, reason)
    if result is None:
        return None
    status, body = result
    response = jsonify(body)
    response.status_code = status
    return response


@app.get("/api/v0/serial/<card_serial>/user")
async def api_user_by_serial(card_serial: str) -> Response:
    """Return the Maker provider user with the given card serial."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_card(card_serial)
    if not user:
        proxied = await _proxied(
            f"/api/v0/serial/{card_serial}/user", proxy_service.REASON_USER_NOT_FOUND
        )
        if proxied is not None:
            return proxied
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
    # Drupal returns an array of one; cardsystem iterates the response, so a
    # bare object would make it iterate dict keys. Match the array shape.
    response = jsonify([payload])
    response.status_code = HTTPStatus.OK
    return response


@app.get("/api/v0/uuid/<user_uuid>/user")
async def api_user_by_uuid(user_uuid: str) -> Response:
    """Return the Maker provider user with the given UUID."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_uuid(user_uuid)
    if not user:
        proxied = await _proxied(
            f"/api/v0/uuid/{user_uuid}/user", proxy_service.REASON_USER_NOT_FOUND
        )
        if proxied is not None:
            return proxied
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
    # Drupal returns an array of one; cardsystem iterates the response, so a
    # bare object would make it iterate dict keys. Match the array shape.
    response = jsonify([payload])
    response.status_code = HTTPStatus.OK
    return response


@app.get("/api/v0/email/<path:email>/user")
async def api_user_by_email(email: str) -> Response:
    """Return the Maker provider user with the given email address."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_email(email)
    if not user:
        proxied = await _proxied(
            f"/api/v0/email/{quote(email, safe=chr(64))}/user", proxy_service.REASON_USER_NOT_FOUND
        )
        if proxied is not None:
            return proxied
        response = jsonify({"error": "User not found for email."})
        response.status_code = HTTPStatus.NOT_FOUND
        return response
    payload = {
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "uuid": user.get("uuid", ""),
        "card_serial": user.get("card_serial", ""),
        "email": user.get("email", ""),
        "access": "Active",
    }
    # Drupal returns an array of one; cardsystem iterates the response, so a
    # bare object would make it iterate dict keys. Match the array shape.
    response = jsonify([payload])
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
        proxied = await _proxied(
            f"/api/v0/serial/{card_serial}/permission/{permission_id}",
            proxy_service.REASON_USER_NOT_FOUND
            if not user
            else proxy_service.REASON_UNKNOWN_PERMISSION,
        )
        if proxied is not None:
            return proxied
        if error_body is None or error_status is None:
            fallback = jsonify({"error": "Permission context unavailable."})
            fallback.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return fallback
        response = jsonify(error_body)
        response.status_code = int(error_status)
        return response
    granted = provider.has_permission(person["id"], permission_id)
    if granted:
        logforward_service.enqueue(
            member_uuid=person.get("uuid", ""),
            permission=permission_id,
            result=True,
            **_forward_fields("card"),
        )
        return _permission_response(person, permission_id, True)
    # A denial is only re-checked upstream when the snapshot is too old to be
    # believed; trusting a fresh local deny is what keeps the common case fast
    # and keeps the box useful during an outage.
    proxied = await _proxied(
        f"/api/v0/serial/{card_serial}/permission/{permission_id}", proxy_service.REASON_PERMISSION_DENIED
    )
    if proxied is not None:
        # Drupal answered this one, and logged it as it did. Forwarding it
        # again would double-count the tap in every report built on the
        # access log.
        return proxied
    logforward_service.enqueue(
        member_uuid=person.get("uuid", ""),
        permission=permission_id,
        result=False,
        **_forward_fields("card", "User does not have the specified permission."),
    )
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
        proxied = await _proxied(
            f"/api/v0/uuid/{user_uuid}/permission/{permission_id}",
            proxy_service.REASON_USER_NOT_FOUND
            if not user
            else proxy_service.REASON_UNKNOWN_PERMISSION,
        )
        if proxied is not None:
            return proxied
        if error_body is None or error_status is None:
            fallback = jsonify({"error": "Permission context unavailable."})
            fallback.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return fallback
        response = jsonify(error_body)
        response.status_code = int(error_status)
        return response
    granted = provider.has_permission(person["id"], permission_id)
    if granted:
        logforward_service.enqueue(
            member_uuid=person.get("uuid", ""),
            permission=permission_id,
            result=True,
            **_forward_fields("uuid"),
        )
        return _permission_response(person, permission_id, True)
    # A denial is only re-checked upstream when the snapshot is too old to be
    # believed; trusting a fresh local deny is what keeps the common case fast
    # and keeps the box useful during an outage.
    proxied = await _proxied(
        f"/api/v0/uuid/{user_uuid}/permission/{permission_id}", proxy_service.REASON_PERMISSION_DENIED
    )
    if proxied is not None:
        # Drupal answered this one, and logged it as it did. Forwarding it
        # again would double-count the tap in every report built on the
        # access log.
        return proxied
    logforward_service.enqueue(
        member_uuid=person.get("uuid", ""),
        permission=permission_id,
        result=False,
        **_forward_fields("uuid", "User does not have the specified permission."),
    )
    return _permission_response(person, permission_id, False)


@app.get("/api/v0/email/<path:email>/permission/<permission_id>")
async def api_permission_by_email(email: str, permission_id: str) -> Response:
    """Return permission info for a user identified by email."""
    provider: AccessProvider = get_provider()
    user = provider.find_user_by_email(email)
    person, _tool, error_body, error_status = _resolve_permission_and_user(
        provider=provider,
        user=user,
        permission_id=permission_id,
    )
    if person is None:
        proxied = await _proxied(
            f"/api/v0/email/{quote(email, safe=chr(64))}/permission/{permission_id}",
            proxy_service.REASON_USER_NOT_FOUND
            if not user
            else proxy_service.REASON_UNKNOWN_PERMISSION,
        )
        if proxied is not None:
            return proxied
        if error_body is None or error_status is None:
            fallback = jsonify({"error": "Permission context unavailable."})
            fallback.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return fallback
        response = jsonify(error_body)
        response.status_code = int(error_status)
        return response
    granted = provider.has_permission(person["id"], permission_id)
    if granted:
        logforward_service.enqueue(
            member_uuid=person.get("uuid", ""),
            permission=permission_id,
            result=True,
            **_forward_fields("email"),
        )
        return _permission_response(person, permission_id, True)
    # A denial is only re-checked upstream when the snapshot is too old to be
    # believed; trusting a fresh local deny is what keeps the common case fast
    # and keeps the box useful during an outage.
    proxied = await _proxied(
        f"/api/v0/email/{quote(email, safe=chr(64))}/permission/{permission_id}", proxy_service.REASON_PERMISSION_DENIED
    )
    if proxied is not None:
        # Drupal answered this one, and logged it as it did. Forwarding it
        # again would double-count the tap in every report built on the
        # access log.
        return proxied
    logforward_service.enqueue(
        member_uuid=person.get("uuid", ""),
        permission=permission_id,
        result=False,
        **_forward_fields("email", "User does not have the specified permission."),
    )
    return _permission_response(person, permission_id, False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)  # noqa: S104


# ----------------------------------------------------------------------
# Background synchronisation lifecycle
# ----------------------------------------------------------------------
@app.before_serving
async def _start_sync() -> None:
    """Restore sync state and, when enabled, start the unattended loop."""
    sync_service.load_state()
    if not CONFIG.SYNC_ENABLED:
        logger.info(
            "Unattended sync is disabled; /health will report an unknown "
            "store age until a store is loaded."
        )
        return
    app.sync_task = asyncio.create_task(sync_service.sync_loop())  # type: ignore[attr-defined]


@app.before_serving
async def _start_log_forward() -> None:
    """Start draining queued decisions back to Drupal.

    Started independently of the sync loop: a box that can no longer *read*
    from Drupal may still be able to write to it, and a queue that stopped
    draining is its own failure with its own signal in ``/health``.
    """
    if not CONFIG.LOG_FORWARD_ENABLED:
        return
    app.log_forward_task = asyncio.create_task(  # type: ignore[attr-defined]
        logforward_service.drain_loop()
    )


@app.after_serving
async def _stop_background_tasks() -> None:
    """Cancel the background loops so shutdown is not held open by a sleep."""
    for attr, label in (("sync_task", "Sync loop"), ("log_forward_task", "Log-forward loop")):
        task = getattr(app, attr, None)
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("%s raised during shutdown.", label)
