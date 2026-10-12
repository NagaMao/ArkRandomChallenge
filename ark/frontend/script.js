const API_BASE = '/api';

// 状态管理
let currentResult = null;
let currentExclude = { operators: [], stages: [] };
let currentTeamSize = 0;

// DOM 引用
const sizeMode = document.getElementById('sizeMode');
const fixedSizeGroup = document.getElementById('fixedSizeGroup');
const rangeSizeGroup = document.getElementById('rangeSizeGroup');
const fixedSize = document.getElementById('fixedSize');
const minSize = document.getElementById('minSize');
const maxSize = document.getElementById('maxSize');
const generateBtn = document.getElementById('generateBtn');
const regenerateBtn = document.getElementById('regenerateBtn');
const resultPanel = document.getElementById('resultPanel');
const teamDisplay = document.getElementById('teamDisplay');
const stageDisplay = document.getElementById('stageDisplay');

// ===== 图片配置 =====
// 头像文件名格式：{干员ID}.png，如 char_1013_chen2.png
// 采用「多源降级」：主源加载失败时依次尝试备用源，全部失败才显示占位符。
// 因为 cdn.jsdelivr.net 在部分网络下会间歇性连接重置，单一 CDN 不够可靠。
const AVATAR_SOURCES = [
    // jsDelivr 的多个节点（fastly / gcore 在国内通常比默认节点稳定）
    'https://fastly.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/avatar/',
    'https://gcore.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/avatar/',
    'https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/avatar/',
    // GitHub 直连（部分网络可用）
    'https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/avatar/',
    // GitHub 代理（兜底）
    'https://gh-proxy.com/https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/avatar/',
];

// 兼容旧引用（日志用）
const AVATAR_CDN_BASE = AVATAR_SOURCES[0];

/**
 * 获取干员头像的主 URL（第一个候选源）
 * @param {string} name - 干员名称（保留备用）
 * @param {string} id - 干员 ID（如 char_1013_chen2）
 * @returns {string} 头像图片 URL
 */
function getOperatorAvatarUrl(name, id) {
    return `${AVATAR_SOURCES[0]}${id}.png`;
}

/**
 * 生成带头像多源降级的 <img> 标签 HTML。
 *
 * 原理：给 img 绑定 onerror，加载失败时按 data-sources 里的候选源依次重试，
 * 全部失败才隐藏 img 并显示占位符。使用内联 onerror 是因为图片是 innerHTML 插入的，
 * 无法单独 addEventListener。
 *
 * @param {string} id - 干员 ID
 * @param {string} name - 干员名称（用于 alt）
 * @param {string} extraClass - 附加到 img 的 class（可选）
 * @returns {string} <img> + 占位符 的 HTML 片段
 */
function buildAvatarHtml(id, name, extraClass = '') {
    const sources = AVATAR_SOURCES.map(base => `${base}${id}.png`);
    // 用 JSON 字符串塞进 data-sources，onerror 里按索引换源
    const sourcesAttr = JSON.stringify(sources).replace(/"/g, '&quot;');
    const cls = extraClass ? `op-avatar ${extraClass}` : 'op-avatar';
    return `
        <img
            src="${sources[0]}"
            alt="${name}"
            class="${cls}"
            loading="lazy"
            data-sources="${sourcesAttr}"
            data-idx="0"
            onerror="window.__avatarFallback && window.__avatarFallback(this)"
        />
                <div class="avatar-placeholder" style="display:none;">🖼️</div>
    `;
}

/**
 * 头像加载失败时的降级处理：按 data-sources 里的下一个候选源重试，
 * 全部失败后隐藏图片、显示占位符。
 */
window.__avatarFallback = function (img) {
    try {
        const sources = JSON.parse(img.dataset.sources || '[]');
        let idx = parseInt(img.dataset.idx || '0', 10);
        idx += 1;
        if (idx < sources.length) {
            img.dataset.idx = String(idx);
            img.src = sources[idx];
        } else {
            // 所有源都失败
            img.style.display = 'none';
            const ph = img.nextElementSibling;
            if (ph && ph.classList.contains('avatar-placeholder')) {
                ph.style.display = 'flex';
            }
        }
    } catch (e) {
        img.style.display = 'none';
        const ph = img.nextElementSibling;
        if (ph && ph.classList.contains('avatar-placeholder')) {
            ph.style.display = 'flex';
        }
    }
};

function clearAllExclude() {
    if (!confirm('确定清空所有黑名单吗？')) return;
    currentExclude = { operators: [], stages: [] };
    saveExcludeLocal();
    renderExclude('operators');
}
// ===== 工具函数 =====

function getSelectedTags(container) {
    const tags = container.querySelectorAll('.tag.active');
    return Array.from(tags).map(t => t.dataset.value);
}

function getStarFilter() {
    const container = document.getElementById('starFilter');
    return getSelectedTags(container).map(Number);
}

function getProfessionFilter() {
    const container = document.getElementById('professionFilter');
    return getSelectedTags(container);
}

function getTeamSize() {
    const mode = sizeMode.value;
    if (mode === 'fixed') {
        return { mode: 'fixed', size: parseInt(fixedSize.value) || 4 };
    } else {
        return { 
            mode: 'range', 
            min: parseInt(minSize.value) || 3,
            max: parseInt(maxSize.value) || 6
        };
    }
}

function getRandomSkill() {
    return document.getElementById('randomSkill').checked;
}

// ===== 标记切换（仅随机挑战页） =====

// 星级/职业标签切换
document.querySelectorAll('#page-challenge .filter-tags .tag').forEach(tag => {
    tag.addEventListener('click', function() {
        this.classList.toggle('active');
    });
});

// 全选/清除按钮（仅随机挑战页）
document.querySelectorAll('#page-challenge .filter-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        const target = this.dataset.target;
        const container = target === 'star' 
            ? document.getElementById('starFilter') 
            : document.getElementById('professionFilter');
        const tags = container.querySelectorAll('.tag');
        const isSelectAll = this.classList.contains('select-all');
        
        tags.forEach(tag => {
            if (isSelectAll) {
                tag.classList.add('active');
            } else {
                tag.classList.remove('active');
            }
        });
    });
});

// 人数模式切换
sizeMode.addEventListener('change', function() {
    if (this.value === 'fixed') {
        fixedSizeGroup.style.display = 'flex';
        rangeSizeGroup.style.display = 'none';
    } else {
        fixedSizeGroup.style.display = 'none';
        rangeSizeGroup.style.display = 'flex';
    }
});

// ===== 黑名单 Tab 切换 =====

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        renderExclude(this.dataset.tab);
    });
});

// ===== API 调用 =====

async function generateTeam() {
    const starFilter = getStarFilter();
    const profFilter = getProfessionFilter();
    const size = getTeamSize();
    const randomSkill = getRandomSkill();
    
    let teamSize;
    if (size.mode === 'fixed') {
        teamSize = size.size;
    } else {
        teamSize = Math.floor(Math.random() * (size.max - size.min + 1)) + size.min;
    }
    currentTeamSize = teamSize;
    
    try {
                const resp = await fetch(`${API_BASE}/random-team`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                teamSize,
                stars: starFilter,
                professions: profFilter,
                randomSkill,
                // 登录状态下，随机池限制为玩家拥有的干员
                ownedIds: sklandAuth.cred ? sklandAuth.ownedIds : null
            })
        });
        
        const result = await resp.json();
        
        if (result.code === 1) {
            alert(result.msg);
            return;
        }
        
        currentResult = result.data;
        renderResult(result.data);
        
    } catch (err) {
        alert('生成失败，请确保后端服务已启动 (python app.py)');
        console.error(err);
    }
}

/**
 * 将干员按竖列优先的顺序重新排列
 */
function reorderTeamForVerticalDisplay(team, teamSize) {
    if (teamSize === 0) return [];
    
    const cols = 6;
    const rows = 2;
    const totalSlots = cols * rows;
    
    const displayTeam = team.slice(0, totalSlots);
    const count = displayTeam.length;
    const result = new Array(totalSlots).fill(null);
    
    for (let i = 0; i < count; i++) {
        const colIndex = Math.floor(i / rows);
        const rowIndex = i % rows;
        const targetIndex = colIndex + rowIndex * cols;
        result[targetIndex] = displayTeam[i];
    }
    
    return result;
}

function renderResult(data) {
    resultPanel.style.display = 'block';
    
    // 关卡
    if (data.stage) {
        const displayName = data.stage.display_name || data.stage.name || data.stage.id;
        stageDisplay.textContent = displayName;
    } else {
        stageDisplay.textContent = '无可用关卡';
    }
    
    // 队伍 - 2行6列布局，竖列优先填充
    const teamSize = data.team_size || data.team.length;
    const totalSlots = 12;
    const orderedTeam = reorderTeamForVerticalDisplay(data.team, teamSize);
    
    let html = '';
    for (let i = 0; i < totalSlots; i++) {
        const op = orderedTeam[i] || null;
        if (op) {
                        const stars = '⭐'.repeat(op.star);
            const skillName = op.selected_skill ? op.selected_skill.name : '';
            
            html += `
                <div class="team-card" data-slot="${i}">
                    <div class="avatar-wrapper">
                        ${buildAvatarHtml(op.id, op.name)}
                    </div>
                    <div class="op-name">${op.name}</div>
                    <span class="star-emoji">${stars}</span>
                    <div class="op-info">${op.profession}</div>
                    ${skillName ? `<div class="op-skill">⚡ ${skillName}</div>` : ''}
                    <button class="exclude-op-btn" data-id="${op.id}">🚫 排除</button>
                </div>
            `;
        } else {
            html += `
                <div class="team-card empty-slot" data-slot="${i}">
                    <span>空位</span>
                </div>
            `;
        }
    }
    
    teamDisplay.innerHTML = html;
    
    // 绑定排除按钮
    document.querySelectorAll('.exclude-op-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const id = this.dataset.id;
            const name = currentResult.team.find(op => op.id === id)?.name || id;
            if (confirm(`确定排除 ${name} 吗？排除后需要重新生成结果。`)) {
                updateExclude('operator', id, 'add');
            }
        });
    });
    
    resultPanel.scrollIntoView({ behavior: 'smooth' });
}

async function updateExclude(type, id, action) {
    try {
        const resp = await fetch(`${API_BASE}/exclude`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, id, action })
        });
        const result = await resp.json();
        if (result.code === 0) {
            currentExclude = result.data;
            renderExclude('operators');
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadExclude() {
    try {
        const resp = await fetch(`${API_BASE}/exclude/list`);
        const result = await resp.json();
        if (result.code === 0) {
            currentExclude = result.data;
            renderExclude('operators');
        }
    } catch (err) {
        console.error(err);
    }
}

function renderExclude(tab = 'operators') {
    const container = document.getElementById('excludeContent');
    const list = currentExclude[tab] || [];
    
    if (list.length === 0) {
        container.innerHTML = `<p class="empty-hint">暂无排除项</p>`;
        return;
    }
    
    const html = list.map(id => {
        let displayName = id;
        if (tab === 'operators') {
            const op = operatorsData?.find(o => o.id === id);
            if (op) displayName = op.name;
        }
        return `
            <span class="exclude-item">
                ${displayName}
                <span class="remove-btn" data-type="${tab.slice(0, -1)}" data-id="${id}">×</span>
            </span>
        `;
    }).join('');
    
    container.innerHTML = `<div class="exclude-list">${html}</div>`;
    
    container.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const type = this.dataset.type === 'operator' ? 'operator' : 'stage';
            const id = this.dataset.id;
            if (confirm(`确定移除排除吗？`)) {
                updateExclude(type, id, 'remove');
            }
        });
    });
}

// ===== 技能开关标签联动 =====
const randomSkillCheckbox = document.getElementById('randomSkill');
const skillLabel = document.getElementById('skillLabel');

if (randomSkillCheckbox && skillLabel) {
    randomSkillCheckbox.addEventListener('change', function() {
        skillLabel.textContent = this.checked ? '开启技能随机' : '关闭技能随机';
    });
}

// ===== 初始化时加载干员数据（用于显示名字） =====
let operatorsData = [];

async function loadOperators() {
    try {
        let url = `${API_BASE}/operators`;
        // 登录状态下，干员一览只显示玩家拥有的干员
        if (sklandAuth.cred && sklandAuth.ownedIds && sklandAuth.ownedIds.length > 0) {
            url += `?owned=${encodeURIComponent(sklandAuth.ownedIds.join(','))}`;
        }
        const resp = await fetch(url);
        const result = await resp.json();
        if (result.code === 0) {
            operatorsData = result.data;
            // 数据就绪后渲染"干员一览"页，并刷新黑名单里的干员名字
            renderOperators();
            renderExclude('operators');
        }
    } catch (err) {
        console.error('加载干员数据失败', err);
    }
}

// ===== 人数输入范围限制 =====

function clampTeamSize(input) {
    let val = parseInt(input.value);
    if (isNaN(val) || val < 1) {
        input.value = 1;
    } else if (val > 12) {
        input.value = 12;
    }
    // 联动校验
    if (input.id === 'minSize') {
        const maxVal = parseInt(maxSize.value) || 6;
        if (parseInt(input.value) > maxVal) input.value = maxVal;
    } else if (input.id === 'maxSize') {
        const minVal = parseInt(minSize.value) || 3;
        if (parseInt(input.value) < minVal) input.value = minVal;
    }
}

// 固定人数
fixedSize.addEventListener('change', () => clampTeamSize(fixedSize));
fixedSize.addEventListener('input', () => clampTeamSize(fixedSize));

// 最小人数
minSize.addEventListener('change', () => clampTeamSize(minSize));
minSize.addEventListener('input', () => clampTeamSize(minSize));

// 最大人数
maxSize.addEventListener('change', () => clampTeamSize(maxSize));
maxSize.addEventListener('input', () => clampTeamSize(maxSize));
// ===== 事件绑定 =====

generateBtn.addEventListener('click', generateTeam);
regenerateBtn.addEventListener('click', generateTeam);

document.getElementById('excludeAllBtn').addEventListener('click', function() {
    if (!currentResult) return;
    const teamIds = currentResult.team.map(op => op.id);
    if (confirm(`确定将当前队伍的 ${teamIds.length} 位干员全部排除吗？`)) {
        teamIds.forEach(id => {
            updateExclude('operator', id, 'add');
        });
        setTimeout(() => loadExclude(), 500);
    }
});

// ===== 顶部导航栏页面切换 =====

document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.addEventListener('click', function() {
        const page = this.dataset.page;

        // 切换页签高亮
        document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        // 切换页面显示
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const target = document.getElementById('page-' + page);
        if (target) target.classList.add('active');

        // 切到干员一览时重新渲染（保证使用最新筛选状态）
        if (page === 'operators') {
            renderOperators();
        }

        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
});

// ===== 干员一览：筛选与渲染 =====

function getOpProfessionFilter() {
    const container = document.getElementById('opProfessionFilter');
    if (!container) return [];
    return getSelectedTags(container);
}

function getOpStarFilter() {
    const container = document.getElementById('opStarFilter');
    if (!container) return [];
    return getSelectedTags(container).map(Number);
}

function renderOperators() {
    const grid = document.getElementById('operatorsGrid');
    const hint = document.getElementById('opCountHint');
    if (!grid) return;

    const professions = getOpProfessionFilter();
    const stars = getOpStarFilter();

    // 筛选：职业、星级（任一为空表示不限制）
    let list = operatorsData || [];
    if (professions.length > 0) {
        list = list.filter(op => professions.includes(op.profession));
    }
    if (stars.length > 0) {
        list = list.filter(op => stars.includes(op.star));
    }

    // 排序：先按星级降序，再按职业，最后按名字
    list = list.slice().sort((a, b) => {
        if (b.star !== a.star) return b.star - a.star;
        if (a.profession !== b.profession) return a.profession.localeCompare(b.profession, 'zh');
        return a.name.localeCompare(b.name, 'zh');
    });

    if (hint) hint.textContent = `共 ${list.length} 位干员`;

    if (list.length === 0) {
        grid.innerHTML = `<p class="empty-hint">没有符合条件的干员</p>`;
        return;
    }

        grid.innerHTML = list.map(op => {
        return `
            <div class="op-card" data-id="${op.id}">
                <div class="op-card-avatar">
                    ${buildAvatarHtml(op.id, op.name)}
                </div>
                <div class="op-card-name">${op.name}</div>
                <div class="op-card-meta">
                    <span class="op-card-star">${'⭐'.repeat(op.star)}</span>
                    <span class="op-card-profession">${op.profession}</span>
                </div>
            </div>
        `;
    }).join('');
}

// 干员一览页的筛选标签交互
(function bindOperatorsFilters() {
    const profContainer = document.getElementById('opProfessionFilter');
    const starContainer = document.getElementById('opStarFilter');

    [profContainer, starContainer].forEach(container => {
        if (!container) return;
        container.querySelectorAll('.tag').forEach(tag => {
            tag.addEventListener('click', function() {
                this.classList.toggle('active');
                renderOperators();
            });
        });
    });

    // 全选 / 清除
    document.querySelectorAll('.filter-btn[data-target^="op-"]').forEach(btn => {
        btn.addEventListener('click', function() {
            const target = this.dataset.target; // op-profession / op-star
            const container = target === 'op-star' ? starContainer : profContainer;
            if (!container) return;

            const isSelectAll = this.classList.contains('select-all');
            container.querySelectorAll('.tag').forEach(tag => {
                tag.classList.toggle('active', isSelectAll);
            });
            renderOperators();
        });
    });
})();

// ===== 森空岛登录 =====

const SKLAND_STORAGE_KEY = 'skland_auth';

// 登录态：{ cred, credToken, accountName, characters: [...], currentUid, ownedIds: [...] }
// credToken 是换取 cred 时同时返回的 token，用作调用森空岛接口时的签名密钥。
let sklandAuth = {
    cred: null,
    credToken: null,
    accountName: '',
    characters: [],
    currentUid: null,
    ownedIds: []
};

// DOM 引用
const loginForm = document.getElementById('loginForm');
const loginStatus = document.getElementById('loginStatus');
const loginPhone = document.getElementById('loginPhone');
const loginPassword = document.getElementById('loginPassword');
const loginCode = document.getElementById('loginCode');
const passwordGroup = document.getElementById('passwordGroup');
const codeGroup = document.getElementById('codeGroup');
const loginBtn = document.getElementById('loginBtn');
const sendCodeBtn = document.getElementById('sendCodeBtn');
const loginError = document.getElementById('loginError');
const accountName = document.getElementById('accountName');
const characterList = document.getElementById('characterList');
const ownedCountHint = document.getElementById('ownedCountHint');
const logoutBtn = document.getElementById('logoutBtn');

let loginMode = 'password'; // password | code

// ---- 本地持久化 ----

function saveAuth() {
    // 只保存必要字段；cred 属于敏感信息，仅存本地
        localStorage.setItem(SKLAND_STORAGE_KEY, JSON.stringify({
        cred: sklandAuth.cred,
        credToken: sklandAuth.credToken,
        accountName: sklandAuth.accountName,
        characters: sklandAuth.characters,
        currentUid: sklandAuth.currentUid,
        ownedIds: sklandAuth.ownedIds
    }));
}

function loadAuth() {
    try {
        const raw = localStorage.getItem(SKLAND_STORAGE_KEY);
        if (!raw) return false;
                const data = JSON.parse(raw);
        if (!data || !data.cred) return false;
        // 旧版本数据可能缺少 credToken，此时视为失效，需重新登录
        if (!data.credToken) {
            localStorage.removeItem(SKLAND_STORAGE_KEY);
            return false;
        }
        sklandAuth = Object.assign(sklandAuth, data);
        return true;
    } catch (e) {
        return false;
    }
}

function clearAuth() {
        localStorage.removeItem(SKLAND_STORAGE_KEY);
    sklandAuth = {
        cred: null,
        credToken: null,
        accountName: '',
        characters: [],
        currentUid: null,
        ownedIds: []
    };
}

// ---- 表单交互 ----

document.querySelectorAll('.login-tab').forEach(tab => {
    tab.addEventListener('click', function () {
        document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        loginMode = this.dataset.mode;
        if (loginMode === 'password') {
            passwordGroup.style.display = 'block';
            codeGroup.style.display = 'none';
        } else {
            passwordGroup.style.display = 'none';
            codeGroup.style.display = 'block';
        }
    });
});

function showLoginError(msg) {
    loginError.textContent = msg || '';
}

sendCodeBtn.addEventListener('click', async function () {
    showLoginError('');
    const phone = loginPhone.value.trim();
    if (!/^\d{6,15}$/.test(phone)) {
        showLoginError('请输入正确的手机号');
        return;
    }
    this.disabled = true;
    this.textContent = '发送中...';
    try {
        const resp = await fetch(`${API_BASE}/skland/login/send-code`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone })
        });
        const result = await resp.json();
        if (result.code !== 0) {
            showLoginError(result.msg || '发送验证码失败');
            this.disabled = false;
            this.textContent = '获取验证码';
            return;
        }
        // 倒计时
        let countdown = 60;
        this.textContent = `${countdown}s`;
        const timer = setInterval(() => {
            countdown--;
            if (countdown <= 0) {
                clearInterval(timer);
                this.disabled = false;
                this.textContent = '获取验证码';
            } else {
                this.textContent = `${countdown}s`;
            }
        }, 1000);
    } catch (err) {
        showLoginError('网络错误，请确保后端服务已启动');
        this.disabled = false;
        this.textContent = '获取验证码';
    }
});

loginBtn.addEventListener('click', async function () {
    showLoginError('');
    const phone = loginPhone.value.trim();
    if (!/^\d{6,15}$/.test(phone)) {
        showLoginError('请输入正确的手机号');
        return;
    }

    let endpoint, body;
    if (loginMode === 'password') {
        const password = loginPassword.value;
        if (!password) {
            showLoginError('请输入密码');
            return;
        }
        endpoint = `${API_BASE}/skland/login/password`;
        body = { phone, password };
    } else {
        const code = loginCode.value.trim();
        if (!code) {
            showLoginError('请输入验证码');
            return;
        }
        endpoint = `${API_BASE}/skland/login/code`;
        body = { phone, code };
    }

    this.disabled = true;
    this.textContent = '登录中...';
    try {
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const result = await resp.json();
        if (result.code !== 0) {
            showLoginError(result.msg || '登录失败');
            return;
        }
                sklandAuth.cred = result.data.cred;
        sklandAuth.credToken = result.data.token;
        sklandAuth.accountName = phone.replace(/^(\d{3})\d+(\d{4})$/, '$1****$2');
        await afterLogin();
    } catch (err) {
        showLoginError('网络错误，请确保后端服务已启动');
    } finally {
        this.disabled = false;
        this.textContent = '登 录';
    }
});

logoutBtn.addEventListener('click', function () {
    if (!confirm('确定退出登录吗？')) return;
    clearAuth();
    renderLoginState();
    // 退出后干员一览恢复全量
    loadOperators();
});

// ---- 登录成功后的流程 ----

async function afterLogin() {
    // 获取绑定角色列表
    try {
        const resp = await fetch(`${API_BASE}/skland/bindings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cred: sklandAuth.cred, token: sklandAuth.credToken })
        });
        const result = await resp.json();
        if (result.code !== 0) {
            showLoginError(result.msg || '获取角色列表失败');
            clearAuth();
            renderLoginState();
            return;
        }
        sklandAuth.characters = result.data.characters || [];
        if (sklandAuth.characters.length === 0) {
            showLoginError('该账号下没有找到明日方舟角色');
            clearAuth();
            renderLoginState();
            return;
        }
        // 默认选择第一个角色
        sklandAuth.currentUid = sklandAuth.characters[0].uid;
        renderLoginState();
        saveAuth();
        await loadOwnedOperators(sklandAuth.currentUid);
    } catch (err) {
        showLoginError('网络错误，请确保后端服务已启动');
    }
}

// 选择角色
async function selectCharacter(uid) {
    if (sklandAuth.currentUid === uid) return;
    sklandAuth.currentUid = uid;
    renderLoginState();
    await loadOwnedOperators(uid);
    saveAuth();
}

// 拉取玩家拥有的干员
async function loadOwnedOperators(uid) {
    ownedCountHint.textContent = '干员数据加载中...';
    try {
        const resp = await fetch(`${API_BASE}/skland/players`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cred: sklandAuth.cred, token: sklandAuth.credToken, uid })
        });
        const result = await resp.json();
        if (result.code !== 0) {
            ownedCountHint.textContent = result.msg || '获取干员数据失败';
            return;
        }
        sklandAuth.ownedIds = result.data.ownedIds || [];
        ownedCountHint.textContent = `已加载 ${sklandAuth.ownedIds.length} 位拥有干员`;
        saveAuth();
        // 干员一览页同步为玩家拥有干员
        loadOperators();
    } catch (err) {
        ownedCountHint.textContent = '网络错误，请确保后端服务已启动';
    }
}

// ---- 渲染登录状态 ----

function renderLoginState() {
    if (sklandAuth.cred) {
        loginForm.style.display = 'none';
        loginStatus.style.display = 'block';
        accountName.textContent = sklandAuth.accountName || '森空岛账号';

        // 角色列表
        characterList.innerHTML = sklandAuth.characters.map(c => {
            const active = c.uid === sklandAuth.currentUid ? 'active' : '';
            const defaultTag = c.isDefault ? '<span class="char-default">默认</span>' : '';
            return `
                <div class="character-item ${active}" data-uid="${c.uid}">
                    <div class="char-name">${c.nickName || c.uid}</div>
                    <div class="char-meta">
                        <span class="char-channel">${c.channelName || '未知'}</span>
                        ${defaultTag}
                    </div>
                </div>
            `;
        }).join('');

        characterList.querySelectorAll('.character-item').forEach(item => {
            item.addEventListener('click', () => selectCharacter(item.dataset.uid));
        });

        if (sklandAuth.ownedIds && sklandAuth.ownedIds.length > 0) {
            ownedCountHint.textContent = `已加载 ${sklandAuth.ownedIds.length} 位拥有干员`;
        } else {
            ownedCountHint.textContent = '干员加载中...';
        }
    } else {
        loginForm.style.display = 'block';
        loginStatus.style.display = 'none';
    }
}
document.getElementById('clearExcludeBtn').addEventListener('click', clearAllExclude);
// ===== 启动 =====

// 先恢复本地登录态，再加载数据（这样干员一览能正确带 owned 参数）
if (loadAuth()) {
    renderLoginState();
}

loadOperators();
loadExclude();

console.log('🎲 明日方舟随机队伍工具已启动！');
console.log('后端 API:', API_BASE);
console.log('头像 CDN:', AVATAR_CDN_BASE);
