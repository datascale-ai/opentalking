# Local Audio + QuickTalk

The full guide has moved to [Model Deployment / Recipes / Local Audio + QuickTalk](recipes/local-quicktalk-audio.md).

This compatibility page keeps old links working. The new deployment structure separates model pages from combined recipes:

- [QuickTalk Overview](quicktalk.md)
- [QuickTalk Local](quicktalk/local.md)
- [Local Audio + QuickTalk](recipes/local-quicktalk-audio.md)

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
