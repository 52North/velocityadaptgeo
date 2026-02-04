// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const sendButton = document.getElementById('sendButton');
const pdfFrame = document.getElementById('pdfFrame');
const pdfViewer = document.getElementById('pdfViewer');
const pdfTitle = document.getElementById('pdfTitle');
const canvasContainer = document.getElementById('canvasContainer');
const floorplanImage = document.getElementById('floorplanImage');
const navigationCanvas = document.getElementById('navigationCanvas');
const placeholder = document.getElementById('placeholder');

let sessionId = sessionStorage.getItem('sessionId');

if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('sessionId', sessionId);
}

// Chat functionality
let isWaitingForResponse = false;
let currentRoute = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    adjustTextareaHeight();
    setupResizeObserver();
});

function setupEventListeners() {
    // Send message on button click
    sendButton.addEventListener("click", async () => {
        const text = userInput.value.trim();
        if (!text) return;

        const new_query = await sendText(text);
        if (!new_query.name) {
            sendMessage(text);
        } else {
            sendMessage(new_query.corrected_query);
        }
    });

    // Send message on Enter (but allow Shift+Enter for new line)
    userInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();

            const text = userInput.value.trim();
            if (!text) return;

            const new_query = await sendText(text);
            if (!new_query.name) {
                sendMessage(text);
            } else {
                sendMessage(new_query.corrected_query);
            }
        }
    });

    // Auto-resize textarea
    userInput.addEventListener('input', adjustTextareaHeight);


}

function adjustTextareaHeight() {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 150) + 'px';
}

/**
 * Setup resize observer to redraw route when image size changes
 */
function setupResizeObserver() {
    // Use ResizeObserver to detect when the image size changes
    const resizeObserver = new ResizeObserver(() => {
        if (currentRoute && canvasContainer.style.display !== 'none') {
            redrawCurrentRoute();
        }
    });

    // Observe the floorplan image
    resizeObserver.observe(floorplanImage);
}

/**
 * Redraw the current route with updated scaling
 */
function redrawCurrentRoute() {
    if (!currentRoute) return;

    // Get the displayed size of the image (after CSS scaling)
    const displayedWidth = floorplanImage.clientWidth;
    const displayedHeight = floorplanImage.clientHeight;

    // Get the natural size
    const naturalWidth = floorplanImage.naturalWidth;
    const naturalHeight = floorplanImage.naturalHeight;

    if (!naturalWidth || !naturalHeight || !displayedWidth || !displayedHeight) {
        return;
    }

    // Calculate scale factor
    const scaleX = displayedWidth / naturalWidth;
    const scaleY = displayedHeight / naturalHeight;

    // Set canvas to displayed size
    navigationCanvas.width = displayedWidth;
    navigationCanvas.height = displayedHeight;
    navigationCanvas.style.width = displayedWidth + 'px';
    navigationCanvas.style.height = displayedHeight + 'px';

    // Draw the route with scaled coordinates
    drawRouteScaled(currentRoute, scaleX, scaleY);
}

async function sendMessage(message) {

    if (!message || isWaitingForResponse) {
        return;
    }

    // Add user message to chat
    addMessage(message, 'user');

    // Clear input
    userInput.value = '';
    adjustTextareaHeight();

    // Disable input while waiting
    isWaitingForResponse = true;
    sendButton.disabled = true;
    userInput.disabled = true;

    // Show loading message
    const loadingMessageElement = addMessage('Thinking...', 'assistant', true);

    try {
        // Send request to backend
        const response = await fetch("/api/ask", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                prompt: message,
                session_id: sessionId,
            }),
        });

        if (!response.ok) {
            throw new Error('Netzwerkfehler');
        }

        const data = await response.json();

        if (data.state?.thread_id) {
            window.appState.sessionId = data.state.thread_id;
        }


        // Remove loading message
        loadingMessageElement.remove();

        // Log Cypher queries to browser console
        if (data.cypher_queries && data.cypher_queries.length > 0) {
            console.log('%c🔍 Neo4j Cypher Queries:', 'color: #4CAF50; font-weight: bold; font-size: 14px;');
            data.cypher_queries.forEach((query, index) => {
                console.log(`%c Query ${index + 1}:`, 'color: #2196F3; font-weight: bold;');
                console.log(query);
            });
        }

        // Add assistant response
        const assistantAnswer = data.answer || data.state?.final_answer || '';
        addMessage(assistantAnswer, 'assistant');

        // Check if response mentions a floor and display it
        detectAndDisplayFloor(assistantAnswer);

        // Check for navigation to a room (check both question and response)
        await checkAndDisplayNavigation(message, assistantAnswer);

    } catch (error) {
        // Remove loading message
        loadingMessageElement.remove();

        // Show error message
        addMessage('Sorry, an error occurred. Please try again.', 'assistant');
        console.error('Error:', error);
    } finally {
        // Re-enable input
        isWaitingForResponse = false;
        sendButton.disabled = false;
        userInput.disabled = false;
        userInput.focus();
    }
}

function addMessage(text, sender, isLoading = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}${isLoading ? ' loading' : ''}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    // Convert line breaks to paragraphs
    const paragraphs = text.split('\n').filter(p => p.trim());
    paragraphs.forEach(paragraph => {
        const p = document.createElement('p');
        p.textContent = paragraph;
        contentDiv.appendChild(p);
    });

    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return messageDiv;
}

function detectAndDisplayFloor(text) {
    const floorPatterns = {
        'KG': /basement|cellar|kg/i,
        'EG': /ground\s+floor|eg(?!\w)/i,
        '1OG': /1st\s+floor|first\s+floor|1og/i,
        '2OG': /2nd\s+floor|second\s+floor|2og/i,
        '3OG': /3rd\s+floor|third\s+floor|3og/i,
        '4OG': /4th\s+floor|fourth\s+floor|4og/i,
        '5OG': /5th\s+floor|fifth\s+floor|5og/i
    };

    for (const [floor, pattern] of Object.entries(floorPatterns)) {
        if (pattern.test(text)) {
            displayFloor(floor);
            break;
        }
    }
}


function displayFloor(floor) {
    if (!floor) {
        return;
    }

    // Update title
    const floorNames = {
        'KG': 'Basement',
        'EG': 'Ground Floor',
        '1OG': '1st Floor',
        '2OG': '2nd Floor',
        '3OG': '3rd Floor',
        '4OG': '4th Floor',
        '5OG': '5th Floor'
    };

    pdfTitle.textContent = floorNames[floor] || 'Floor View';

    // If there's a current navigation route for 2OG, don't override with PDF
    if (currentRoute && floor === '2OG') {
        return;
    }

    // Show floor view (hide canvas)ss
    showfloorView(floor);
}

// Add some helper functions for potential future features
function clearChat() {
    chatMessages.innerHTML = '';
    addMessage('Chat has been cleared. How can I help you?', 'assistant');
}

function exportChat() {
    const messages = Array.from(chatMessages.querySelectorAll('.message'));
    const chatText = messages.map(msg => {
        const sender = msg.classList.contains('user') ? 'User' : 'Assistant';
        const content = msg.querySelector('.message-content').textContent;
        return `${sender}: ${content}`;
    }).join('\n\n');

    const blob = new Blob([chatText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-export-${new Date().toISOString().split('T')[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

async function sendText(text) {
    const res = await fetch("http://localhost:8000/text_to_query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
    const data = await res.json();
    console.log("name:", data.name, "match:", data.match, "corrected_query:", data.corrected_query);
    return await data;
}



// ============================================
// NAVIGATION FUNCTIONALITY
// ============================================

/**
 * Check if text contains a navigable room and display navigation
 */
async function checkAndDisplayNavigation(question, response) {
    try {
        // Check both the question and response for room numbers
        const textToCheck = `${question} ${response}`;

        const navResponse = await fetch(`/api/check-navigation?text=${encodeURIComponent(textToCheck)}`);

        if (!navResponse.ok) {
            return;
        }

        const navData = await navResponse.json();

        if (navData.found && navData.route) {
            currentRoute = navData.route;
            await displayNavigationRoute(navData.route);
        }
    } catch (error) {
        console.error('Navigation check failed:', error);
    }
}

/**
 * Display the floor plan with navigation route
 */
async function displayNavigationRoute(route) {
    // Hide PDF frame and placeholder
    pdfFrame.style.display = 'none';
    placeholder.style.display = 'none';

    // Show canvas container and navigation canvas
    canvasContainer.style.display = 'flex';
    navigationCanvas.style.display = 'block';

    // Floor name mapping
    const floorNames = {
        'KG': 'Basement',
        'EG': 'Ground Floor',
        '1OG': '1st Floor',
        '2OG': '2nd Floor',
        '3OG': '3rd Floor',
        '4OG': '4th Floor',
        '5OG': '5th Floor'
    };

    // Update title with correct floor name
    const floorName = floorNames[route.floor] || route.floor;
    pdfTitle.textContent = `${floorName} - Route to Room ${route.target_room}`;


    // Store current route for scaling
    currentRoute = route;

    // Load the floor plan image
    const imagePath = `/${route.image}`;

    return new Promise((resolve, reject) => {
        floorplanImage.onload = () => {
            // Wait a bit for the image to be rendered with CSS scaling
            setTimeout(() => {
                // Get the displayed size of the image (after CSS scaling)
                const displayedWidth = floorplanImage.clientWidth;
                const displayedHeight = floorplanImage.clientHeight;

                // Get the natural size
                const naturalWidth = floorplanImage.naturalWidth;
                const naturalHeight = floorplanImage.naturalHeight;

                // Calculate scale factor
                const scaleX = displayedWidth / naturalWidth;
                const scaleY = displayedHeight / naturalHeight;

                // Set canvas to displayed size
                navigationCanvas.width = displayedWidth;
                navigationCanvas.height = displayedHeight;
                navigationCanvas.style.width = displayedWidth + 'px';
                navigationCanvas.style.height = displayedHeight + 'px';

                console.log('Natural size:', naturalWidth, 'x', naturalHeight);
                console.log('Displayed size:', displayedWidth, 'x', displayedHeight);
                console.log('Scale:', scaleX, scaleY);

                // Draw the route with scaled coordinates
                drawRouteScaled(route, scaleX, scaleY);
                resolve();
            }, 100);
        };

        floorplanImage.onerror = () => {
            console.error('Failed to load floor plan image');
            reject(new Error('Failed to load image'));
        };

        floorplanImage.src = imagePath;
    });
}

/**
 * Draw the navigation route on the canvas with scaling
 */
function drawRouteScaled(route, scaleX, scaleY) {
    const ctx = navigationCanvas.getContext('2d');
    const coords = route.coordinates;

    console.log('drawRouteScaled called with scale:', scaleX, scaleY);

    if (!coords || coords.length < 2) {
        console.error('Invalid coordinates:', coords);
        return;
    }

    // Scale coordinates
    const scaledCoords = coords.map(([x, y]) => [x * scaleX, y * scaleY]);

    // Clear canvas
    ctx.clearRect(0, 0, navigationCanvas.width, navigationCanvas.height);

    // Draw the path
    ctx.strokeStyle = '#FF0000';
    ctx.lineWidth = Math.max(4, 6 * Math.min(scaleX, scaleY));
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    ctx.beginPath();
    ctx.moveTo(scaledCoords[0][0], scaledCoords[0][1]);

    for (let i = 1; i < scaledCoords.length; i++) {
        ctx.lineTo(scaledCoords[i][0], scaledCoords[i][1]);
    }
    ctx.stroke();

    // Draw direction arrows along the path
    drawDirectionArrowsScaled(ctx, scaledCoords, scaleX, scaleY);

    // Draw start point (blue circle)
    const pointRadius = Math.max(8, 12 * Math.min(scaleX, scaleY));
    drawPoint(ctx, scaledCoords[0][0], scaledCoords[0][1], '#2196F3', pointRadius, 'START');

    // Draw end point (green circle) at the door
    const doorX = route.door_node.x * scaleX;
    const doorY = route.door_node.y * scaleY;
    drawPoint(ctx, doorX, doorY, '#4CAF50', pointRadius + 3, `Room ${route.target_room}`);

    console.log('Route drawing complete');
}

/**
 * Draw direction arrows along the path (scaled version)
 */
function drawDirectionArrowsScaled(ctx, coords, scaleX, scaleY) {
    // 20% größer als Ursprungsgröße (6 * 1.2 = 7.2)
    const arrowSize = 7.2;

    for (let i = 0; i < coords.length - 1; i++) {
        const startX = coords[i][0];
        const startY = coords[i][1];
        const endX = coords[i + 1][0];
        const endY = coords[i + 1][1];

        // Calculate midpoint
        const midX = (startX + endX) / 2;
        const midY = (startY + endY) / 2;

        // Calculate angle
        const angle = Math.atan2(endY - startY, endX - startX);

        ctx.save();
        ctx.translate(midX, midY);
        ctx.rotate(angle);

        // Weißer Rand für bessere Sichtbarkeit
        ctx.strokeStyle = 'white';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(arrowSize, 0);
        ctx.lineTo(-arrowSize / 2, -arrowSize / 2);
        ctx.lineTo(-arrowSize / 2, arrowSize / 2);
        ctx.closePath();
        ctx.stroke();

        // Roter Pfeil
        ctx.fillStyle = '#FF0000';
        ctx.beginPath();
        ctx.moveTo(arrowSize, 0);
        ctx.lineTo(-arrowSize / 2, -arrowSize / 2);
        ctx.lineTo(-arrowSize / 2, arrowSize / 2);
        ctx.closePath();
        ctx.fill();

        ctx.restore();
    }
}

/**
 * Draw the navigation route on the canvas (original, unscaled version)
 */
function drawRoute(route) {
    const ctx = navigationCanvas.getContext('2d');
    const coords = route.coordinates;

    console.log('drawRoute called with:', coords);
    console.log('Canvas size:', navigationCanvas.width, 'x', navigationCanvas.height);

    if (!coords || coords.length < 2) {
        console.error('Invalid coordinates:', coords);
        return;
    }

    // Clear canvas
    ctx.clearRect(0, 0, navigationCanvas.width, navigationCanvas.height);

    // Draw the path
    ctx.strokeStyle = '#FF0000';
    ctx.lineWidth = 8;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    ctx.beginPath();
    ctx.moveTo(coords[0][0], coords[0][1]);
    console.log('Move to:', coords[0][0], coords[0][1]);

    for (let i = 1; i < coords.length; i++) {
        ctx.lineTo(coords[i][0], coords[i][1]);
        console.log('Line to:', coords[i][0], coords[i][1]);
    }
    ctx.stroke();

    // Draw direction arrows along the path
    drawDirectionArrows(ctx, coords);

    // Draw start point (blue circle)
    drawPoint(ctx, coords[0][0], coords[0][1], '#2196F3', 15, 'START');

    // Draw end point (green circle) at the door
    const doorX = route.door_node.x;
    const doorY = route.door_node.y;
    drawPoint(ctx, doorX, doorY, '#4CAF50', 18, `Room ${route.target_room}`);

    console.log('Route drawing complete');
}

/**
 * Draw direction arrows along the path
 */
function drawDirectionArrows(ctx, coords) {
    ctx.fillStyle = '#FF0000';

    for (let i = 0; i < coords.length - 1; i++) {
        const startX = coords[i][0];
        const startY = coords[i][1];
        const endX = coords[i + 1][0];
        const endY = coords[i + 1][1];

        // Calculate midpoint
        const midX = (startX + endX) / 2;
        const midY = (startY + endY) / 2;

        // Calculate angle
        const angle = Math.atan2(endY - startY, endX - startX);

        // Draw arrow at midpoint
        const arrowSize = 24;  // TEST: doppelt so groß (war 12)

        ctx.save();
        ctx.translate(midX, midY);
        ctx.rotate(angle);

        ctx.beginPath();
        ctx.moveTo(arrowSize, 0);
        ctx.lineTo(-arrowSize / 2, -arrowSize / 2);
        ctx.lineTo(-arrowSize / 2, arrowSize / 2);
        ctx.closePath();
        ctx.fill();

        ctx.restore();
    }
}

/**
 * Draw a labeled point on the canvas
 */
function drawPoint(ctx, x, y, color, radius, label) {
    // Draw outer circle (white border)
    ctx.beginPath();
    ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
    ctx.fillStyle = 'white';
    ctx.fill();

    // Draw inner circle
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Draw label
    ctx.font = 'bold 16px Arial';
    ctx.fillStyle = 'white';
    ctx.strokeStyle = 'black';
    ctx.lineWidth = 3;
    ctx.textAlign = 'center';

    // Background for text
    const textY = y - radius - 10;
    ctx.strokeText(label, x, textY);
    ctx.fillText(label, x, textY);
}

/**
 * Switch between PDF view and Canvas navigation view
 */
function showfloorView(floor) {
    // Hide canvas
    canvasContainer.style.display = 'none';
    pdfFrame.style.display = 'none';

    // Show floor image in the canvas container
    const imagePath = `/floorplans/${floor}.png`;
    floorplanImage.src = imagePath;
    canvasContainer.style.display = 'block';

    // Hide the navigation canvas (just show the image)
    navigationCanvas.style.display = 'none';
    placeholder.style.display = 'none';

    currentRoute = null;
}




// ============================================
// Voice to Qiery functionality
// ============================================



const btn = document.getElementById("pttButton");

// press voice button
function startPress(e) {
    e.preventDefault();
    btn.classList.add("is-pressed");
    startRecording();
}

// if release voice button
function endPress() {
    btn.classList.remove("is-pressed");
    stopRecording();
}

// using mouse
btn.addEventListener("mousedown", startPress);
window.addEventListener("mouseup", endPress);

// using touch
btn.addEventListener("touchstart", startPress, { passive: false });
window.addEventListener("touchend", endPress);
window.addEventListener("touchcancel", endPress);

// safety: if you alt-tab while holding
window.addEventListener("blur", endPress);


/**
 * Audio recording and upload
 */
let mediaRecorder;
let chunks = [];

async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    chunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

    mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
        // stream sauber stoppen
        stream.getTracks().forEach((t) => t.stop());

        const blob = new Blob(chunks, { type: "audio/webm" });
        await uploadAudio(blob);
    };

    mediaRecorder.start();
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
}


/**
 * upload audio file to backend
 * @param {*} blob 
 */
async function uploadAudio(blob) {
    const form = new FormData();
    //console.log("blob type:", blob.type, "blob size:", blob.size);
    form.append("file", blob, "recording.webm");

    const res = await fetch("http://localhost:8000/voice_to_query", {
        method: "POST",
        body: form,
    });

    const data = await res.json();

    console.log(
        "the query result:", data,
        "the name result:", data.result?.name,
        "the match result:", data.result?.match,
        "the corrected query result:", data.result?.corrected_query
    );
    //addMessage(data.corrected_query, 'user');

    sendMessage(data.result?.corrected_query);
}
