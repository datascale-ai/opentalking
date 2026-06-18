# 优云智算镜像快速体验

本页介绍如何在优云智算平台使用已发布的 OpenTalking 镜像完成一次快速体验。全流程只需要在平台页面和 OpenTalking Studio 页面中点击操作。

- 镜像地址：<https://www.compshare.cn/images/TdDwmKZUZebI>
- 浏览器访问入口：5173
- 默认体验链路：OpenTalking Studio + OmniRT + QuickTalk

文档中的截图已对账号、余额、实例标识、公网地址、二维码等敏感信息做打码处理。

## 1. 注册并完成认证

如果还没有优云智算账号，打开镜像页面后按页面提示进入注册页。你可以选择“手机号注册”或“邮箱注册”。以手机号注册为例，填写手机号，点击“获取验证码”，输入验证码，勾选服务协议，然后点击“立即注册”。已有账号可以点击“登录已有账号”。

![注册优云智算账号](../../assets/images/compshare-redacted/register-image.png)

注册后如果弹出“实名领赠金”窗口，选择符合自己身份的卡片。个人用户通常选择“个人开发者/研究员”或“个人爱好者”，然后点击右下角的“前往认证”。

![选择认证身份并前往认证](../../assets/images/compshare-redacted/register-get5yuan.png)

进入“实名认证”页面后，选择对应认证类型。个人用户点击“个人认证”卡片中的“立即认证”；高校或企业用户按自己的组织类型点击对应卡片中的“立即认证”。

![进入实名认证页面](../../assets/images/compshare-redacted/get5yuan.png)

如果页面显示扫码认证，用手机扫描页面中的二维码并按手机端提示完成授权。截图中的二维码已打码，实际操作时请扫描你自己页面上显示的二维码。

![扫码完成实名认证授权](../../assets/images/compshare-redacted/scan-to-authorize.png)

## 2. 从镜像页创建实例

打开 OpenTalking 镜像页面后，确认页面标题为 OpenTalking。右侧操作区有“使用该镜像创建实例”按钮，点击它进入实例部署页面。

![点击使用该镜像创建实例](../../assets/images/compshare-redacted/image.png)

## 3. 选择实例配置

进入部署页面后，先选择地域。建议优先选择有空闲资源的地域；如果某个地域或卡型显示资源不足，可以切换到其他地域或 GPU 型号。

在“实例配置”区域，依次确认“实例类型”“GPU 型号”“GPU 数量”和“CPU 配置”。快速体验建议使用单卡实例，GPU 数量选择 1 即可。

![选择地域、GPU 和 CPU 配置](../../assets/images/compshare-redacted/choose-config.png)

继续向下检查存储配置和右侧“当前配置”。确认无误后，在“付款方式”中选择合适的计费方式，然后点击右下角“立即部署”。

![确认配置并点击立即部署](../../assets/images/compshare-redacted/getconfig.png)

## 4. 等待实例运行

部署提交后，回到“实例列表”。实例刚创建时会显示“初始化”等状态，此时等待即可；如果列表没有变化，可以点击右上角刷新按钮。

![等待实例初始化](../../assets/images/compshare-redacted/listofhosts.png)

当实例状态变为“运行中”后，实例卡片右侧会出现多个操作按钮。快速体验 OpenTalking 时，点击“WebUI”。如果需要确认后端服务入口，也可以在同一行看到“Omnirt-Quicktalk”按钮。

![实例运行后点击 WebUI](../../assets/images/compshare-redacted/host-running.png)

## 5. 打开 OpenTalking Studio

点击“WebUI”后，浏览器会打开 OpenTalking Studio。首次进入时，页面可能显示“未连接”或正在准备资源；等待页面右上角变为“已连接”即可继续。

在左侧“静态配置”区域确认语音和识别服务配置。如果你需要填写自己的服务密钥，在对应输入框填入后点击“应用配置”。

中间“形象库”选择一个数字人形象，右侧确认“已选驱动模型”为 QuickTalk 且显示“已连接”，然后点击“开始对话”。

![应用配置并开始对话](../../assets/images/compshare-redacted/config-to-submit.png)

如果页面提示“正在准备当前形象资产”或按钮显示“准备资产中...”，等待准备完成。首次选择形象时需要生成缓存，后续再次使用会更快。

![等待形象资产准备完成](../../assets/images/compshare-redacted/wait-to-config.png)

连接成功后，可以在底部输入框输入一句话并发送，也可以点击麦克风按钮进行语音输入。右侧“会话面板”会显示对话记录，画面中会播放数字人回复。

![实时对话页面](../../assets/images/compshare-redacted/realtime-talking.png)

## 6. 体验视频创作和音色复刻

如需生成一段离线口播视频，点击顶部导航中的“视频创作”。左侧选择一个形象，中间选择“离线数字人口播”，模型选择 QuickTalk，任务类型选择“数字人口播视频”。

在“音频来源”中可以选择“上传音频”“文本合成”或“复刻音色”。如果要体验音色复刻，点击“复刻音色”，填写口播文本，选择音色后点击“录制/上传复刻”。

![进入视频创作并选择复刻音色](../../assets/images/compshare-redacted/videocreation-clone-tone.png)

弹出的“音色复刻”面板会给出朗读文本。按提示录制或上传音频文件，确认音频可播放后点击提交按钮，等待复刻任务完成。

![提交音色复刻任务](../../assets/images/compshare-redacted/submitting-clone.png)

音色复刻完成后，回到视频创作页面。可以点击“试听口播”先确认声音效果，也可以点击“生成并保存”。生成完成后，右侧“生成结果”区域会出现视频预览，并提供“下载”和“去资产库查看”按钮。

![生成结果并下载或进入资产库](../../assets/images/compshare-redacted/voice-clone-success.png)

## 7. 常见情况

- 点击“WebUI”后页面短时间空白：先等待实例完成自启动；首次启动和首次准备形象资产都需要一点时间。
- 页面右上角显示“未连接”：等待一会儿后刷新页面；如果仍未连接，回到实例列表确认实例状态是否为“运行中”。
- 找不到入口：在实例卡片右侧点击“WebUI”，不要点击浏览器里的其他历史标签页。
- 语音输入不可用：浏览器可能限制公网页面的麦克风权限，首次体验可以直接使用文本输入。
- 想重新开始：回到实例列表，点击实例右侧“更多操作”，按平台页面提供的选项重启实例。
