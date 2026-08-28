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
const AVATAR_CDN_BASE = 'https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/avatar/';

/**
 * 获取干员头像 URL
 * @param {string} name - 干员名称（保留备用）
 * @param {string} id - 干员 ID（如 char_1013_chen2）
 * @returns {string} 头像图片 URL
 */
function getOperatorAvatarUrl(name, id) {
    return `${AVATAR_CDN_BASE}${id}.png`;
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

// ===== 标记切换 =====

// 星级/职业标签切换
document.querySelectorAll('.filter-tags .tag').forEach(tag => {
    tag.addEventListener('click', function() {
        this.classList.toggle('active');
    });
});

// 全选/清除按钮
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
                randomSkill
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
            if (confirm(`确定排除 ${name} 吗？`)) {
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
        const resp = await fetch(`${API_BASE}/operators`);
        const result = await resp.json();
        if (result.code === 0) {
            operatorsData = result.data;
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

// ===== 启动 =====

loadOperators();
loadExclude();

console.log('🎲 明日方舟随机队伍工具已启动！');
console.log('后端 API:', API_BASE);
console.log('头像 CDN:', AVATAR_CDN_BASE);
