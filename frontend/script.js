// === AUTHENTICATION STATE ===
let authToken = null;
let currentUser = null;
let currentConversationId = null;

// === AUTH UI FUNCTIONS ===
function showLogin() {
    document.getElementById('login-tab').classList.add('active');
    document.getElementById('register-tab').classList.remove('active');
    document.getElementById('login-form').style.display = 'flex';
    document.getElementById('register-form').style.display = 'none';
    document.getElementById('login-error').textContent = '';
    document.getElementById('register-error').textContent = '';
}

function showRegister() {
    document.getElementById('register-tab').classList.add('active');
    document.getElementById('login-tab').classList.remove('active');
    document.getElementById('register-form').style.display = 'flex';
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('login-error').textContent = '';
    document.getElementById('register-error').textContent = '';
}

function showMainInterface() {
     console.log('showMainInterface called'); // ← ADD THIS
    document.getElementById('auth-container').style.display = 'none';
    document.getElementById('main-container').style.display = 'block';
    document.getElementById('username-display').textContent = `Hello, ${currentUser}!`;
    toggleWelcomeScreen(true);
    loadConversations();
    updateFileDropdown();
}

async function loadConversations() {
    console.log('loadConversations called, currentConversationId:', currentConversationId); // ← ADD THIS
    try {
        const response = await fetch('http://127.0.0.1:5000/conversations', {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        console.log('Conversations loaded:', data.conversations.length); // ← ADD THIS
        displayConversations(data.conversations);
    } catch (error) {
        console.error('Error loading conversations:', error);
    }
}

function displayConversations(conversations) {
    const listContainer = document.getElementById('conversations-list');    
    listContainer.innerHTML = '';
    
    if (!conversations || conversations.length === 0) {
        listContainer.innerHTML = '<p style="text-align:center;color:#999;padding:20px;">No conversations yet</p>';
        return;
    }
    
    const groups = {
        today: [],
        yesterday: [],
        last7days: [],
        older: []
    };
    
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    const sevenDaysAgo = new Date(today);
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    
    conversations.forEach(conv => {
        const convDate = new Date(conv.updated_at);
        const convDay = new Date(convDate.getFullYear(), convDate.getMonth(), convDate.getDate());
        
        if (convDay.getTime() === today.getTime()) {
            groups.today.push(conv);
        } else if (convDay.getTime() === yesterday.getTime()) {
            groups.yesterday.push(conv);
        } else if (convDay >= sevenDaysAgo) {
            groups.last7days.push(conv);
        } else {
            groups.older.push(conv);
        }
    });
    
    if (groups.today.length > 0) {
        listContainer.appendChild(createConversationGroup('Today', groups.today));
    }
    if (groups.yesterday.length > 0) {
        listContainer.appendChild(createConversationGroup('Yesterday', groups.yesterday));
    }
    if (groups.last7days.length > 0) {
        listContainer.appendChild(createConversationGroup('Last 7 Days', groups.last7days));
    }
    if (groups.older.length > 0) {
        listContainer.appendChild(createConversationGroup('Older', groups.older));
    }
}

function createConversationGroup(title, conversations) {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'conversation-group';
    
    const titleDiv = document.createElement('div');
    titleDiv.className = 'conversation-group-title';
    titleDiv.textContent = title;
    groupDiv.appendChild(titleDiv);
    
    conversations.forEach(conv => {
        const convItem = document.createElement('div');
        convItem.className = 'conversation-item';
        convItem.dataset.convId = conv.id;
        
        if (conv.id === currentConversationId) {
            convItem.classList.add('active');
        }
        
        const titleSpan = document.createElement('span');
        titleSpan.className = 'conversation-title';
        titleSpan.textContent = conv.title;
        
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'delete-conversation';
        deleteBtn.textContent = 'Delete';
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteConversation(conv.id);
        };
        
        convItem.appendChild(titleSpan);
        convItem.appendChild(deleteBtn);
        convItem.onclick = () => loadConversation(conv.id);
        
        groupDiv.appendChild(convItem);
    });
    
    return groupDiv;
}

async function loadConversation(convId) {
    try {
        toggleWelcomeScreen(false);
        const response = await fetch(`http://127.0.0.1:5000/conversations/${convId}`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const conversation = await response.json();
        currentConversationId = convId;
        
        const chatWindow = document.getElementById('chatwindow');
        chatWindow.innerHTML = '';
        
        conversation.messages.forEach(msg => {
            if (msg.role === 'user') {
                addMessageToUI('You', msg.content, 'user-message');
            } else {
                addMessageToUI('Bot', msg.content, 'bot-message');
            }
        });
        
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.convId === convId) {
                item.classList.add('active');
            }
        });
        
    } catch (error) {
        console.error('Error loading conversation:', error);
    }
}

// === DELETE CONVERSATION ===
async function deleteConversation(convId) {
    if (!confirm('Delete this conversation?')) return;
    
    try {
        const response = await fetch(`http://127.0.0.1:5000/conversations/${convId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (response.ok) {
            if (convId === currentConversationId) {
                currentConversationId = null;
                document.getElementById('chatwindow').innerHTML = '';
            }
            loadConversations();
        }
    } catch (error) {
        console.error('Error deleting conversation:', error);
    }
}

// === ADD MESSAGE TO UI ===
function addMessageToUI(sender, text, className, citations = [], quality = 'relevant') {
    const chatwindow = document.getElementById('chatwindow');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${className}`;

    const senderSpan = document.createElement('strong');
    senderSpan.textContent = sender + ": ";

    const textSpan = document.createElement('span');
    textSpan.textContent = text;

    messageDiv.appendChild(senderSpan);
    messageDiv.appendChild(textSpan);

    // ── Quality warning badge (shown only if grader flagged it) ──
    if (className === 'bot-message' && quality === 'not_relevant') {
        const badge = document.createElement('div');
        badge.style.cssText = `
            margin-top: 8px;
            padding: 4px 10px;
            background: #3d2000;
            border: 1px solid #ff8c00;
            border-radius: 6px;
            color: #ff8c00;
            font-size: 12px;
            display: inline-block;
        `;
        badge.textContent = '⚠️ This answer may not fully address your question.';
        messageDiv.appendChild(badge);
    }

    // ── Citation pills (shown only for bot messages with citations) ──
    if (className === 'bot-message' && citations.length > 0) {
        const citationContainer = document.createElement('div');
        citationContainer.style.cssText = 'margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px;';

        const label = document.createElement('span');
        label.style.cssText = 'width: 100%; font-size: 11px; color: #666; margin-bottom: 2px;';
        label.textContent = 'Sources:';
        citationContainer.appendChild(label);

        citations.forEach((cite, i) => {
            const pill = document.createElement('a');
            pill.href = cite.url;
            pill.target = '_blank';
            pill.rel = 'noopener noreferrer';
            pill.title = cite.snippet;   // shows snippet on hover
            pill.style.cssText = `
                padding: 3px 10px;
                background: #1a1a2e;
                border: 1px solid #0f3460;
                border-radius: 20px;
                color: #4da6ff;
                font-size: 12px;
                text-decoration: none;
                transition: background 0.2s;
            `;
            // Show domain name only, e.g. "cardekho.com"
            try {
                const domain = new URL(cite.url).hostname.replace('www.', '');
                pill.textContent = `[${i + 1}] ${domain}`;
            } catch {
                pill.textContent = `[${i + 1}] Source`;
            }
            pill.onmouseover = () => pill.style.background = '#0f3460';
            pill.onmouseout = () => pill.style.background = '#1a1a2e';
            citationContainer.appendChild(pill);
        });

        messageDiv.appendChild(citationContainer);
    }

    chatwindow.appendChild(messageDiv);
    chatwindow.scrollTop = chatwindow.scrollHeight;
    return textSpan;  // return so streaming can append to it
}

// === SEND MESSAGE ===
async function sendMessage() {
    const userInput = document.getElementById('userinput');
    const message = userInput.value.trim();
    toggleWelcomeScreen(false);

    if (!message) return;
    if (!authToken) { alert('Please login first'); return; }

    addMessageToUI("You", message, "user-message");
    userInput.value = "";

    // 1. Create the bot message bubble immediately (empty, will fill live)
    const chatwindow = document.getElementById('chatwindow');
    const botDiv = document.createElement('div');
    botDiv.className = 'message bot-message';

    const senderSpan = document.createElement('strong');
    senderSpan.textContent = "Bot: ";

    const textSpan = document.createElement('span');
    textSpan.textContent = "";  // starts empty, tokens get appended here

    // Blinking cursor shown while streaming
    const cursor = document.createElement('span');
    cursor.id = 'streaming-cursor';
    cursor.textContent = '▋';
    cursor.style.cssText = 'animation: blink 1s step-end infinite; margin-left: 2px;';

    botDiv.appendChild(senderSpan);
    botDiv.appendChild(textSpan);
    botDiv.appendChild(cursor);
    chatwindow.appendChild(botDiv);
    chatwindow.scrollTop = chatwindow.scrollHeight;

    try {
        const toolsAllowed = {
            "search_knowledge_base": document.getElementById('toggle-kb').classList.contains('active'),
            "web_search": document.getElementById('toggle-web').classList.contains('active')
        };
        const targetFile = toolsAllowed.search_knowledge_base 
            ? document.getElementById('file-target-selector').value 
            : "all";
        const response = await fetch('http://127.0.0.1:5000/chat/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
                tools_allowed: toolsAllowed
            },
            body: JSON.stringify({
                message: message,
                conversation_id: currentConversationId,
                target_file: targetFile,
                tools_allowed: toolsAllowed
            })
        });

        if (!response.ok) {
            cursor.remove();
            textSpan.textContent = "Error: Server returned " + response.status;
            return;
        }

        // 3. Read the stream chunk by chunk
        const reader = response.body.getReader();
        const decoder = new TextDecoder(); // converts raw bytes → text

        while (true) {
            const { done, value } = await reader.read();
            if (done) break; // stream closed by server

            // Decode the raw bytes into a string
            const chunk = decoder.decode(value, { stream: true });

            // Each SSE message looks like: "data: {...}\n\n"
            // Split by double newline to get individual messages
            const lines = chunk.split('\n\n');

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue; // skip empty lines

                const jsonStr = line.replace('data: ', '').trim();
                if (!jsonStr) continue;

                try {
                    const parsed = JSON.parse(jsonStr);

                    if (parsed.error) {
                        // Backend sent an error mid-stream
                        cursor.remove();
                        textSpan.textContent = "Error: " + parsed.error;
                        break;
                    }
                    if (parsed.status) {
                        // Remove any existing status indicator first
                        // (in case two tools run back to back)
                        const existing = botDiv.querySelector('.tool-status');
                        if (existing) existing.remove();

                        // Build the indicator message
                        const messages = {
                            'searching_web': '🌐 Searching the internet...',
                            'searching_kb':  '📚 Searching your documents...',
                            'getting_time':  '🕐 Getting current time...'
                        };
                        const text = messages[parsed.status] || '⚙️ Working...';

                        // Create the animated status pill
                        const statusEl = document.createElement('div');
                        statusEl.className = 'tool-status';
                        statusEl.style.cssText = `
                            margin-top: 6px;
                            padding: 4px 12px;
                            background: #1a1a2e;
                            border: 1px solid #0f3460;
                            border-radius: 20px;
                            color: #4da6ff;
                            font-size: 12px;
                            display: inline-flex;
                            align-items: center;
                            gap: 6px;
                            animation: pulse 1.5s ease-in-out infinite;
                        `;
                        statusEl.innerHTML = `<span class="status-dot"></span>${text}`;
                        botDiv.appendChild(statusEl);
                        chatwindow.scrollTop = chatwindow.scrollHeight;
                    }

                    if (parsed.token) {
                        // Append this token to the visible message
                        textSpan.textContent += parsed.token;
                        chatwindow.scrollTop = chatwindow.scrollHeight; // auto-scroll
                    }

                    if (parsed.done) {
                        // Stream is finished
                        botDiv.querySelector('.tool-status')?.remove();
                        cursor.remove(); // remove blinking cursor

                        // Update conversation ID if this was a new conversation
                        if (parsed.conv_id) {
                            const wasNew = !currentConversationId;
                            currentConversationId = parsed.conv_id;
                            if (wasNew) setTimeout(() => loadConversations(), 300);
                        }
                        const citations = parsed.citations || [];
                        const quality = parsed.quality || 'relevant';

                        if (quality === 'not_relevant') {
                            const badge = document.createElement('div');
                            badge.style.cssText = `
                                margin-top: 8px; padding: 4px 10px;
                                background: #3d2000; border: 1px solid #ff8c00;
                                border-radius: 6px; color: #ff8c00;
                                font-size: 12px; display: inline-block;
                            `;
                            badge.textContent = '⚠️ This answer may not fully address your question.';
                            botDiv.appendChild(badge);
                        }

                        if (citations.length > 0) {
                            const citationContainer = document.createElement('div');
                            citationContainer.style.cssText = 'margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px;';

                            const label = document.createElement('span');
                            label.style.cssText = 'width: 100%; font-size: 11px; color: #666; margin-bottom: 2px;';
                            label.textContent = 'Sources:';
                            citationContainer.appendChild(label);

                            citations.forEach((cite, i) => {
                                const pill = document.createElement('a');
                                pill.href = cite.url;
                                pill.target = '_blank';
                                pill.rel = 'noopener noreferrer';
                                pill.title = cite.snippet;
                                pill.style.cssText = `
                                    padding: 3px 10px; background: #1a1a2e;
                                    border: 1px solid #0f3460; border-radius: 20px;
                                    color: #4da6ff; font-size: 12px;
                                    text-decoration: none;
                                `;
                                try {
                                    const domain = new URL(cite.url).hostname.replace('www.', '');
                                    pill.textContent = `[${i + 1}] ${domain}`;
                                } catch {
                                    pill.textContent = `[${i + 1}] Source`;
                                }
                                citationContainer.appendChild(pill);
                            });

                            botDiv.appendChild(citationContainer);
                            chatwindow.scrollTop = chatwindow.scrollHeight;
                        }
                    }

                } catch (parseErr) {
                    // Malformed JSON in a chunk — skip it
                    console.warn('Could not parse SSE chunk:', jsonStr);
                }
            }
        }

    } catch (error) {
        cursor.remove();
        textSpan.textContent = "Server connection failed.";
        console.error('Stream error:', error);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Check if user is already logged in
    authToken = localStorage.getItem('auth_token');
    currentUser = localStorage.getItem('username');
    
    if (authToken && currentUser) {
        showMainInterface();
    }

    // tool logic
    const toolToggles = document.querySelectorAll('.tool-toggle');
    toolToggles.forEach(toggle => {
        toggle.addEventListener('click', () => {
            toggle.classList.toggle('active');
        });
    });

    // === LOGIN HANDLER ===
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        const errorElement = document.getElementById('login-error');
        
        errorElement.textContent = 'Logging in...';
        errorElement.style.color = '#3498db';
        
        try {
            const response = await fetch('http://127.0.0.1:5000/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                authToken = data.token;
                currentUser = data.username;
                
                localStorage.setItem('auth_token', authToken);
                localStorage.setItem('username', currentUser);
                localStorage.setItem('user_id', data.user_id);
                
                showMainInterface();
            } else {
                errorElement.style.color = '#e74c3c';
                errorElement.textContent = data.detail || 'Login failed';
            }
        } catch (error) {
            errorElement.style.color = '#e74c3c';
            errorElement.textContent = 'Connection error. Is the server running?';
            console.error('Login error:', error);
        }
    });

    // === REGISTER HANDLER ===
    document.getElementById('register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('register-username').value;
        const password = document.getElementById('register-password').value;
        const errorElement = document.getElementById('register-error');
        
        errorElement.textContent = 'Creating account...';
        errorElement.style.color = '#3498db';
        
        try {
            const response = await fetch('http://127.0.0.1:5000/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                errorElement.style.color = '#27ae60';
                errorElement.textContent = 'Account created! Please login.';
                
                setTimeout(() => {
                    showLogin();
                    document.getElementById('login-username').value = username;
                }, 1500);
            } else {
                errorElement.style.color = '#e74c3c';
                errorElement.textContent = data.detail || 'Registration failed';
            }
        } catch (error) {
            errorElement.style.color = '#e74c3c';
            errorElement.textContent = 'Connection error. Is the server running?';
            console.error('Register error:', error);
        }
    });

    // === LOGOUT HANDLER ===
    document.getElementById('logout-button').addEventListener('click', () => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('username');
        localStorage.removeItem('user_id');
        
        document.getElementById('chatwindow').innerHTML = '';
        
        authToken = null;
        currentUser = null;
        currentConversationId = null;
        
        document.getElementById('main-container').style.display = 'none';
        document.getElementById('auth-container').style.display = 'flex';
        
        document.getElementById('login-username').value = '';
        document.getElementById('login-password').value = '';
    });

    // === NEW CHAT BUTTON ===
    document.getElementById('new-chat-button').addEventListener('click', () => {
        currentConversationId = null;
        document.getElementById('chatwindow').innerHTML = '';
        toggleWelcomeScreen(true);
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.remove('active');
        });
    });

    // === CHAT EVENT LISTENERS ===
    const sendButton = document.getElementById('sendbutton');
    const userInput = document.getElementById('userinput');

    sendButton.addEventListener('click', () => {
        sendMessage();
    });
    
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const statusDiv = document.getElementById('uploadStatus');
    const file = fileInput.files[0];

    if (!file) return;

    statusDiv.innerText = "⏳ Reading & Learning...";
    statusDiv.style.color = "#FFD700"; // Gold

    const formData = new FormData();
    formData.append('file', file);

    try {
        // 2. Send to Backend
        const response = await fetch('http://127.0.0.1:5000/upload-doc', {
            method: 'POST',
            headers: {  
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });

        const data = await response.json();
        
        if (data.status === "success") {
            statusDiv.innerText = "✅ Knowledge Added!";
            updateFileDropdown();
            statusDiv.style.color = "#4caf50";
            fileInput.value = ""; 
            
            setTimeout(() => { statusDiv.innerText = ""; }, 3000);
        } else {
            statusDiv.innerText = "❌ Error: " + data.message;
            statusDiv.style.color = "#f44336";
        }
    } catch (error) {
        statusDiv.innerText = "❌ Server Error";
        statusDiv.style.color = "#f44336";
        console.error('Upload error:', error);
    }
}

// === FILE MANAGER LOGIC ===

function openFileManager() {
    document.getElementById('file-modal').style.display = 'flex';
    loadUserFiles();
}

function closeFileManager() {
    document.getElementById('file-modal').style.display = 'none';
}

async function loadUserFiles() {
    const fileList = document.getElementById('file-list');
    fileList.innerHTML = '<p style="text-align: center; color: #888;">Loading files...</p>';

    try {
        const response = await fetch('http://127.0.0.1:5000/files', {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        
        if (data.status === "success") {
            renderFiles(data.files);
        } else {
            fileList.innerHTML = `<p style="color: #ff4757; text-align: center;">Error: ${data.message}</p>`;
        }
    } catch (error) {
        fileList.innerHTML = '<p style="color: #ff4757; text-align: center;">Connection error.</p>';
    }
}

function renderFiles(files) {
    const fileList = document.getElementById('file-list');
    fileList.innerHTML = '';

    if (!files || files.length === 0) {
        fileList.innerHTML = '<p style="text-align: center; color: #888;">No files uploaded yet.</p>';
        return;
    }

    files.forEach(file => {
        const date = new Date(file.uploaded_at).toLocaleDateString();
        
        const fileDiv = document.createElement('div');
        fileDiv.className = 'file-item';
        
        fileDiv.innerHTML = `
            <div class="file-item-info">
                <span class="file-name" title="${file.filename}">${file.filename}</span>
                <span class="file-date">Uploaded: ${date}</span>
            </div>
            <button class="delete-file-btn" onclick="deleteFile('${file.id}')">Delete</button>
        `;
        
        fileList.appendChild(fileDiv);
    });
}

async function deleteFile(fileId) {
    if (!confirm("Are you sure? This will delete the file and remove its knowledge from the AI.")) return;

    try {
        const response = await fetch(`http://127.0.0.1:5000/files/${fileId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        
        if (data.status === "success") {
            // Reload the list to show it's gone
            loadUserFiles(); 
            updateFileDropdown();
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (error) {
        alert('Connection error while trying to delete.');
    }
}



// Mem0 MEMORY MANAGER LOGIC 

function openMemoryManager() {
    document.getElementById('memory-modal').style.display = 'flex';
    loadUserMemories();
}

function closeMemoryManager() {
    document.getElementById('memory-modal').style.display = 'none';
}

async function loadUserMemories() {
    const memoryList = document.getElementById('memory-list');
    memoryList.innerHTML = '<p style="text-align: center; color: #888;">Accessing long-term memory...</p>';

    try {
        const response = await fetch('http://127.0.0.1:5000/memories', {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        
        if (data.status === "success") {
            renderMemories(data.memories);
        } else {
            memoryList.innerHTML = `<p style="color: #ff4757; text-align: center;">Error: ${data.message}</p>`;
        }
    } catch (error) {
        memoryList.innerHTML = '<p style="color: #ff4757; text-align: center;">Connection error.</p>';
    }
}

function renderMemories(memories) {
    const memoryList = document.getElementById('memory-list');
    memoryList.innerHTML = '';

    if (!memories || memories.length === 0) {
        memoryList.innerHTML = '<p style="text-align: center; color: #888;">Argus hasn\'t memorized anything about you yet.</p>';
        return;
    }

    memories.forEach(mem => {
        // Handle dates gracefully if they don't exist yet
        const dateStr = mem.date ? new Date(mem.date).toLocaleDateString() : 'Recently';
        
        const memDiv = document.createElement('div');
        // Reusing the file-item CSS classes so it looks identical to the file manager!
        memDiv.className = 'file-item'; 
        
        memDiv.innerHTML = `
            <div class="file-item-info" style="flex: 1; padding-right: 15px;">
                <span class="file-name" style="white-space: normal; line-height: 1.4;" title="${mem.text}">${mem.text}</span>
                <span class="file-date">Learned: ${dateStr}</span>
            </div>
            <button class="delete-file-btn" onclick="deleteMemory('${mem.id}')">Forget</button>
        `;
        
        memoryList.appendChild(memDiv);
    });
}

async function deleteMemory(memoryId) {
    if (!confirm("Are you sure? Argus will permanently forget this fact about you.")) return;

    try {
        const response = await fetch(`http://127.0.0.1:5000/memories/${memoryId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        
        if (data.status === "success") {
            // Reload the list to show the memory is gone
            loadUserMemories(); 
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (error) {
        alert('Connection error while trying to delete memory.');
    }
}

// === UPDATE DROPDOWN ===
async function updateFileDropdown() {
    const selector = document.getElementById('file-target-selector');
    if (!selector) return;

    // Reset it back to just the default option
    selector.innerHTML = '<option value="all">Search All Files</option>';

    if (!authToken) return;

    try {
        const response = await fetch('http://127.0.0.1:5000/files', {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        const data = await response.json();
        
        if (data.status === "success" && data.files) {
            data.files.forEach(file => {
                const option = document.createElement('option');
                option.value = file.filename; 
                
                // Truncate name if it's too long so it doesn't break the UI
                const displayName = file.filename.length > 20 
                    ? file.filename.substring(0, 20) + '...' 
                    : file.filename;
                    
                option.textContent = displayName;
                selector.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error fetching files for dropdown:', error);
    }
}

function toggleWelcomeScreen(show) {
    const welcomeScreen = document.getElementById('welcome-screen');
    const chatWindow = document.getElementById('chatwindow');
    
    // Grab the main chatbox container
    const chatbox = document.querySelector('.chatbox'); 
    
    if (show) {
        welcomeScreen.classList.remove('hidden');
        chatWindow.classList.add('hidden');
        
        // Add the class to push everything to the center
        chatbox.classList.add('centered-state'); 
        
        if (typeof currentUser !== 'undefined') {
            document.getElementById('welcome-greeting').textContent = `Hi ${currentUser}`; 
        }
    } else {
        welcomeScreen.classList.add('hidden');
        chatWindow.classList.remove('hidden');
        
        // Remove the class to drop the input box to the bottom
        chatbox.classList.remove('centered-state'); 
    }
}