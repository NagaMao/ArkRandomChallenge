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
const AVATAR_CDN_BASE = 'https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/avatar/';

function getOperatorAvatarUrl(name, id) {
    return `${AVATAR_CDN_BASE}${id}.png`;
}

// ===== 黑名单（localStorage 本地存储） =====

const EXCLUDE_KEY = 'arknights_exclude';

function loadExcludeLocal() {
    try {
        const raw = localStorage.getItem(EXCLUDE_KEY);
        if (raw) {
            const data = JSON.parse(raw);
            currentExclude = {
                operators: data.operators || [],
                stages: data.stages || []
            };
        } else {
            currentExclude = { operators: [], stages: [] };
        }
    } catch (e) {
        currentExclude = { operators: [], stages: [] };
    }
    renderExclude('operators');
}

function saveExcludeLocal() {
    localStorage.setItem(EXCLUDE_KEY, JSON.stringify(currentExclude));
}

function updateExclude(type, id, action) {
    const key = type === 'operator' ? 'operators' : 'stages';
    if (action === 'add') {
        if (!currentExclude[key].includes(id)) {
            currentExclude[key].push(id);
        }
    } else if (action === 'remove') {
        currentExclude[key] = currentExclude[key].filter(x => x !== id);
    }
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

function getRandomSkill() {
    return document.getElementById('randomSkill').checked;
}

/**
 * 校验人数输入是否合法（1~12 的纯数字）
 */
function validateSizeInput(input) {
    const raw = input.value.trim();
    if (!/^\d+$/.test(raw)) {
        return { ok: false, value: 0 };
    }
    const val = parseInt(raw, 10);
    if (val < 1 || val > 12) {
        return { ok: false, value: val };
    }
    return { ok: true, value: val };
}

// ===== 标记切换 =====

document.querySelectorAll('.filter-tags .tag').forEach(tag => {
    tag.addEventListener('click', function() {
        this.classList.toggle('active');
    });
});

document.querySelectorAll('.filter-btn').forEach(btn => {
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
    const randomSkill = getRandomSkill();
    
    // ===== 人数校验 =====
    const mode = sizeMode.value;
    let teamSize;
    
    if (mode === 'fixed') {
        const check = validateSizeInput(fixedSize);
        if (!check.ok) {
            alert('队伍人数请输入1~12的数字');
            fixedSize.focus();
            return;
        }
        teamSize = check.value;
    } else {
        const checkMin = validateSizeInput(minSize);
        if (!checkMin.ok) {
            alert('队伍人数请输入1~12的数字');
            minSize.focus();
            return;
        }
        const checkMax = validateSizeInput(maxSize);
        if (!checkMax.ok) {
            alert('队伍人数请输入1~12的数字');
            maxSize.focus();
            return;
        }
        if (checkMin.value > checkMax.value) {
            alert('最小人数不能大于最大人数');
            minSize.focus();
            return;
        }
        teamSize = Math.floor(Math.random() * (checkMax.value - checkMin.value + 1)) + checkMin.value;
    }
    
    currentTeamSize = teamSize;
    
    // 把本地黑名单一起发给后端
    try {
        const resp = await fetch(`${API_BASE}/random-team`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                teamSize,
                stars: starFilter,
                professions: profFilter,
                randomSkill,
                exclude: currentExclude
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
 * PC 端（6列2行）用竖列优先，其他布局用行优先
 */
function reorderTeamForVerticalDisplay(team, teamSize) {
    if (teamSize === 0) return [];
    
    const gridEl = document.getElementById('teamDisplay');
    const style = getComputedStyle(gridEl);
    const cols = parseInt(style.getPropertyValue('--team-cols')) || 6;
    const rows = parseInt(style.getPropertyValue('--team-rows')) || 2;
    const totalSlots = cols * rows;
    
    const displayTeam = team.slice(0, totalSlots);
    const count = displayTeam.length;
    const result = new Array(totalSlots).fill(null);
    
    if (cols === 6 && rows === 2) {
        // PC 端：竖列优先
        for (let i = 0; i < count; i++) {
            const colIndex = Math.floor(i / rows);
            const rowIndex = i % rows;
            const targetIndex = colIndex + rowIndex * cols;
            result[targetIndex] = displayTeam[i];
        }
    } else {
        // 手机/平板：行优先
        for (let i = 0; i < count; i++) {
            result[i] = displayTeam[i];
        }
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
    
    // 队伍
    const teamSize = data.team_size || data.team.length;
    const gridEl = document.getElementById('teamDisplay');
    const style = getComputedStyle(gridEl);
    const cols = parseInt(style.getPropertyValue('--team-cols')) || 6;
    const rows = parseInt(style.getPropertyValue('--team-rows')) || 2;
    const totalSlots = cols * rows;
    
    const orderedTeam = reorderTeamForVerticalDisplay(data.team, teamSize);
    
    let html = '';
    for (let i = 0; i < totalSlots; i++) {
        const op = orderedTeam[i] || null;
        if (op) {
            const stars = '⭐'.repeat(op.star);
            const skillName = op.selected_skill ? op.selected_skill.name : '';
            const avatarUrl = getOperatorAvatarUrl(op.name, op.id);
            
            html += `
                <div class="team-card" data-slot="${i}">
                    <div class="avatar-wrapper">
                        <img 
                            src="${avatarUrl}" 
                            alt="${op.name}" 
                            class="op-avatar"
                            loading="lazy"
                            onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                        />
                        <div class="avatar-placeholder" style="display:none;">🖼️</div>
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

// ===== 初始化时加载干员数据 =====
let operatorsData = [];

async function loadOperators() {
    try {
        const resp = await fetch(`${API_BASE}/operators`);
        const result = await resp.json();
        if (result.code === 0) {
            operatorsData = result.data;
            // 干员数据加载完成后，重新渲染黑名单以显示正确名字
            renderExclude('operators');
        }
    } catch (err) {
        console.error('加载干员数据失败', err);
    }
}

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
    }
});

// ===== 启动 =====

loadOperators();
loadExcludeLocal();

console.log('🎲 明日方舟随机队伍工具已启动！');
console.log('后端 API:', API_BASE);
console.log('头像 CDN:', AVATAR_CDN_BASE);