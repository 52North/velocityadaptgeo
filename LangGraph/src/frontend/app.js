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

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}`
    );

    evtSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const step = data.metadata?.langgraph_step;
        const content = data.content;

        if (!step) return;

        // Step change, now a new tool is talking.
        if (step !== currentStep) {
            currentStep = step;
            currentStepMessage = null;
        }

        if (!currentStepMessage) {
            currentStepMessage = addMessage("assistant", "");
        }

        // Streaming text for fancy output
        if (content) {
            currentStepMessage.innerHTML += content;
        }

        // Rendering artifact geometry on map
        if (data.artifact?.structured_content) {

            const geometry = data.artifact.structured_content;

            console.log("Artifact received:");
            console.log(data.artifact);

            console.log("Structured geometry:");
            console.log(geometry);

            try {
                if (currentGeometryLayer) {
                    map.removeLayer(currentGeometryLayer);
                }

                currentGeometryLayer = L.geoJSON(geometry).addTo(map);
                map.fitBounds(currentGeometryLayer.getBounds());

                console.log("Geometry rendered successfully.");
            } catch (err) {
                console.error("Failed to render geometry:", err);
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
