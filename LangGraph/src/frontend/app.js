const form = document.getElementById("chat-form");
const input = document.getElementById("prompt");

function addMessage(role, text = "") {
    const div = document.createElement("div");
    div.classList.add("message", role);
    div.textContent = text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

form.addEventListener("submit", (e) => {
    e.preventDefault();

    const prompt = input.value.trim();
    if (!prompt) return;

    addMessage("user", prompt);
    input.value = "";

    let currentStep = null;
    let currentStepMessage = null;
    let currentStepText = "";

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}`
    );

    evtSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const messageType = data.type; 
        const step = data.metadata?.langgraph_step;
        const node = data.metadata?.langgraph_node;
        const content = data.content;

        if (!step) return;

        if (step !== currentStep) {
            currentStep = step;
            currentStepMessage = null;
            currentStepText = "";
        }

        if (!currentStepMessage) {
            currentStepMessage = addMessage("assistant", "");
            currentStepMessage.classList.add(`type-${messageType}`);
            
            if (node) {
                currentStepMessage.classList.add(`node-${node}`);
            }
            if (node === "manager") {
                        // Much cleaner, styling moved to CSS
                        currentStepMessage.innerHTML = `
                            <details class="manager-details">
                                <summary>Manager Activity</summary>
                                <pre class="content"></pre>
                            </details>
                        `;
                    }
        }

        if (content) {
            currentStepText += content;
            
            const targetContainer = node === "manager" 
                ? currentStepMessage.querySelector('.content') 
                : currentStepMessage;

            if (messageType === "tool") {
                currentStepMessage.style.fontStyle = "italic";
                currentStepMessage.style.color = "#666";
                
                try {
                    const parsedContent = JSON.parse(currentStepText);
                    
                    if (parsedContent.message && parsedContent.structured_content) {
                        // It's our map output
                        targetContainer.innerHTML = `<strong>Action (${node}):</strong> ${parsedContent.message}`;
                        
                        const geoJsonFeature = {
                            "type": "Feature",
                            "geometry": parsedContent.structured_content,
                            "properties": {}
                        };

                        if (currentGeometryLayer) {
                            map.removeLayer(currentGeometryLayer);
                        }
                        currentGeometryLayer = L.geoJSON(geoJsonFeature).addTo(map);
                        map.fitBounds(currentGeometryLayer.getBounds());
                        
                    } else {
                        // FIX: It is valid JSON, but not a map output. Render it readable.
                        targetContainer.innerHTML = `<strong>Action (${node}):</strong><br/>
                        <pre style="margin: 5px 0 0 0; font-size: 0.9em;">${JSON.stringify(parsedContent, null, 2)}</pre>`;
                    }
                    
                } catch (e) {
                    // It is incomplete or plain text
                    targetContainer.innerHTML = currentStepText.replace(/\n/g, '<br>');
                }
                } else if (node === "manager") {
                // Strip the ```json and ``` backticks from the text
                targetContainer.textContent = currentStepText.replace(/```(json)?/gi, '').trim();
            } else {
                targetContainer.innerHTML = currentStepText.replace(/\n/g, '<br>');
            }
        }

        chat.scrollTop = chat.scrollHeight;
    };


    evtSource.onerror = () => {
        evtSource.close();
        if (currentStepMessage) {
            currentStepMessage.classList.remove("streaming");
            currentStepMessage.classList.add("final");
        }
    };
});

// Leaflet Map Setup
const map = L.map("map").setView([52.52, 13.405], 13); // Muenster default

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

let currentGeometryLayer = null;
