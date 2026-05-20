---
id: flow-simulation
title: Flow Simulation
sidebar_label: Flow Simulation
---

# Flow Simulation

The **Flow Simulator** and **API Tester** let you test your flow logic before routing any live calls through it.

## Flow Simulator

The Flow Simulator is built into the Flow Editor. It lets you step through a conversation manually, providing mock caller responses at each Collect Slot node.

### Starting a Simulation

1. Open the Flow Editor for your assistant.
2. Click the **Simulate** button in the toolbar.
3. A chat-style panel opens on the right side of the canvas.

### How to Use It

- The simulator begins at the **Start** node and shows the initial message.
- When a **Collect Slot** node is reached, type your mock response in the input box.
- When an **API Request** node is reached, you can either:
  - Let it make a real outbound request (if the API is accessible), or
  - Enter a **mock response** JSON body to simulate the API's response
- The active node is highlighted on the canvas as the simulation progresses.

### Inspecting Variables

At any point in the simulation, click **Variables** in the simulator panel to see the current state of all variables captured so far.

### Ending a Simulation

Click **Stop** or let the flow reach an **End** node. The simulator resets to the beginning.

---

## API Tester

The **API Tester** is a separate tool for testing the API Request node's configuration against a live external API endpoint — without running a full call simulation.

### Accessing the API Tester

Go to **Tools** → **API Tester** in the left sidebar, or click **Test API** from within an API Request node's configuration panel.

### Using the API Tester

1. Select an existing **Account Integration** or enter a custom URL manually.
2. Set the HTTP method, headers, and body.
3. Fill in variable values (these replace `{{variable}}` placeholders in the URL and body).
4. Click **Send Request**.
5. The response body, status code, and latency are shown.

This is useful for:
- Verifying authentication headers are correct
- Confirming the response shape matches your response mapping configuration
- Debugging connection timeouts or 4xx/5xx errors

### API Tester and Account Secrets

When testing a request that uses `{{secret.MY_KEY}}` in headers, the API Tester automatically substitutes the encrypted secret value without exposing it in the UI.

---

## Testing Before Going Live

We recommend this sequence before enabling a flow on a live phone number:

1. **Flow Simulator** — step through every branch with representative caller inputs
2. **API Tester** — verify each external API call returns the expected data
3. **Test call** — dial the number from a personal phone and walk through the real IVR
4. **Call Logs review** — confirm the transcript, events, and ACW score look correct
