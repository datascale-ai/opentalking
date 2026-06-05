# V100 + FasterLivePortrait + FlashHead Deployment Recipe

This V100 deployment recipe is currently maintained in Chinese:

[Read the Chinese guide](https://datascale-ai.github.io/opentalking/model-deployment/recipes/v100-fasterliveportrait-flashhead/).

It covers a single NVIDIA V100 32GB host running OpenTalking with:

- FasterLivePortrait through OmniRT for real-person video-driven rendering.
- FlashHead through a WebSocket bridge for image-conditioned generation.
- V100-specific notes for FP16, TensorRT 8.6, disabled `torch.compile`, CUDA libraries, and WebRTC port exposure.
