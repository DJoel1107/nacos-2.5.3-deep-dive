# 第1章：Nacos 2.5.3 整体架构概述

## 1.1 Nacos 定位与核心能力矩阵

**【设计背景】**

Nacos（Dynamic Naming and Configuration Service）是阿里巴巴开源的生产级中间件，在云原生微服务体系中承担**服务发现（Service Discovery）**和**配置管理（Configuration Management）**双重核心角色。与 Spring Cloud Alibaba、Dubbo、gRPC 等主流微服务生态深度集成。Nacos 2.5.3 相比 2.2.3，Java 文件总数从 1,925 增至 2,460（+535），新增 `persistence/` 独立持久化模块和 `logger-adapter-impl/` 日志适配器模块。

Nacos 的核心定位可概括为三大能力域：服务发现、配置管理和服务治理。这三者构成了云原生微服务基础设施的完整能力矩阵。

**与其他注册中心的对比**：与 Eureka（AP，Client-side LB，仅支持 HTTP REST）、Consul（CP，Agent-based 健康检查，支持 DNS/gRPC）、ZooKeeper（CP，临时节点 + Watcher，无原生配置管理）相比，Nacos 的差异化定位在于：同时支持 AP/CP 双协议（通过 `ephemeral` 字段灵活切换）、原生配置管理能力（无需额外部署配置中心）、gRPC Bi-directional Stream 长连接推送（延迟 < 50ms vs HTTP 短轮询 15-30s）。这种"三大能力合一"的设计使得中小团队只需部署一个中间件即可获得完整的微服务基础设施能力——无需像"Eureka + Config + Sentinel"那样维护三个独立的中间件及其版本兼容性矩阵。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-1</span><span class="tt">Nacos 2.5.3 三大核心能力域与外部生态集成全景</span><span class="src">基于 Nacos 2.5.3 源码</span></div>
<div class="dgm-eco">
<div class="dgm-ecochip"><b>Spring Cloud Alibaba</b><span>服务发现 + 配置管理</span></div>
<div class="dgm-varrow"></div>
<div class="dgm-ecochip"><b>Dubbo</b><span>RPC 服务注册与发现</span></div>
<div class="dgm-varrow dgm-varrow--accent"></div>
</div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Nacos 2.5.3</span><span class="s">Dynamic Naming &amp; Configuration Service</span><span class="tag">ONE MIDDLEWARE</span></div>
<div class="dgm-panel-body">
<div class="dgm-cols dgm-cols-3">
<div class="dgm-card dgm-card--deep"><div class="h"><span class="k">Discovery</span><span class="t">服务发现</span><span class="m">naming 模块</span></div><ul><li>服务注册</li><li>服务发现</li><li>健康检查</li><li>AP（Distro 协议）</li><li>CP（JRaft 协议）</li></ul></div>
<div class="dgm-card dgm-card--bright"><div class="h"><span class="k">Configuration</span><span class="t">配置管理</span><span class="m">config 模块</span></div><ul><li>配置发布</li><li>配置订阅</li><li>灰度发布</li><li>历史回滚</li><li>Beta / Tag 发布</li></ul></div>
<div class="dgm-card dgm-card--ink"><div class="h"><span class="k">Governance</span><span class="t">服务治理</span><span class="m">Sentinel 集成</span></div><ul><li>流量控制</li><li>熔断降级</li><li>负载均衡</li><li>热点防护</li><li>系统自适应保护</li></ul></div>
</div>
<div class="dgm-layer">
<div class="dgm-layer-label"><span class="zh">底层能力</span><span class="en">Foundation</span></div>
<div class="dgm-layer-body">
<div class="dgm-cols dgm-cols-3">
<div><div class="dgm-chip" style="border:none;padding:0 0 4px;font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.1em;color:var(--text-helper);text-transform:uppercase;">通信协议</div><div class="dgm-chips"><span class="dgm-chip"><b>gRPC</b> 双向流</span><span class="dgm-chip">HTTP REST</span><span class="dgm-chip">DNS-F</span></div></div>
<div><div class="dgm-chip" style="border:none;padding:0 0 4px;font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.1em;color:var(--text-helper);text-transform:uppercase;">存储后端</div><div class="dgm-chips"><span class="dgm-chip">Derby（内置）</span><span class="dgm-chip">MySQL（生产集群）</span></div></div>
<div><div class="dgm-chip" style="border:none;padding:0 0 4px;font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.1em;color:var(--text-helper);text-transform:uppercase;">一致性协议</div><div class="dgm-chips"><span class="dgm-chip">Distro <span class="dgm-badge dgm-badge--ap">AP</span></span><span class="dgm-chip">JRaft <span class="dgm-badge dgm-badge--cp">CP</span></span></div></div>
</div>
</div>
</div>
</div>
</div>
<div class="dgm-eco">
<div class="dgm-varrow"></div>
<div class="dgm-ecochip"><b>gRPC Ecosystem</b><span>Bi-directional Stream 长连接推送</span></div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 的三大核心能力在源码层面有明确的模块边界：

**一、服务发现（Naming Module）**

服务发现的核心入口为 `InstanceController`（naming/src/main/java/com/alibaba/nacos/naming/controllers/InstanceController.java:1-466），提供 `register()` 方法（第 113-129 行）处理客户端服务注册请求。注册流程如下：

1. `InstanceController.register()`（:113-129）解析请求参数：`namespaceId`、`groupName`、`serviceName`，经 `HttpRequestInstanceBuilder`（:120-121）从请求参数中构建出 `Instance` 对象
2. `ServiceManager.getSingleton(Service)`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/ServiceManager.java:61）在 `singletonRepository`（:38）中通过 `computeIfAbsent` 惰性注册或获取 Service 单例
3. `client.addServiceInstance(service, instanceInfo)` 将 Instance 写入该 Client 的实例发布信息（ephemeral 与 persistent 语义由实例 `ephemeral` 字段决定）
4. `ClientOperationServiceProxy.registerInstance(service, instance, clientId)`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/service/ClientOperationServiceProxy.java:55-58）按 `instance.isEphemeral()`（:88-90）路由：`true` → `EphemeralClientOperationServiceImpl`（AP，Distro 协议去中心化同步），`false` → `PersistentClientOperationServiceImpl`（CP，JRaft 协议 Raft 日志复制）

服务发现的查询入口为 `InstanceController.list()`，返回过滤健康实例的 JSON 响应。

**二、配置管理（Config Module）**

配置管理的核心入口为 `ConfigController`（config/src/main/java/com/alibaba/nacos/config/server/controller/ConfigController.java:1-1016）。`publishConfig()` 方法（第 156-200 行）处理配置发布：白名单校验 → 参数合法性验证 → 持久化服务写入 MySQL（生产）/ Derby（单机）→ `ConfigCacheService.dump()` 将新配置从数据库装载到本地缓存并更新 MD5，供长轮询比对 → `NotifyCenter.publishEvent(ConfigDataChangeEvent)` 异步通知已订阅客户端。

配置订阅基于 `LongPollingService`（config/src/main/java/com/alibaba/nacos/config/server/service/LongPollingService.java）：客户端发起长轮询请求，服务端持有连接最多 29.5 秒，配置发生变更时立即返回新配置内容；若超时无变更，返回空响应，客户端重新发起长轮询。

**三、服务治理（Sentinel 集成）**

Nacos 2.5.3 本身不内置流量控制引擎，而是通过与 Sentinel 集成实现服务治理能力。Sentinel 以 Nacos 作为动态规则数据源，将流量控制规则、熔断降级规则、热点参数规则等持久化在 Nacos 配置中心，Sentinel 客户端通过 Nacos SDK 订阅规则变更，实现动态规则实时生效。

**【trade-off 分析】**

Nacos 三大核心能力矩阵的设计涉及以下关键权衡：

1. **三大能力合一 vs 独立部署**：将服务发现、配置管理、服务治理统一集成在 Nacos 中，用户只需部署一个中间件即可获得三大核心能力，运维成本低。但代价是耦合风险——如果 Config 模块出现故障，虽然理论上不影响 Naming 模块独立运行（2.5.3 支持模块独立启动），但共享 JVM 进程意味着 Config 模块的内存泄漏或 CPU 飙高会影响 Naming 模块响应延迟。如果拆分为三个独立中间件，虽然隔离性更好，但运维成本增加三倍。

2. **Sentinel 集成 vs 内置流量控制**：Nacos 选择与 Sentinel 集成实现服务治理（而非内置流量控制引擎），保持了 Nacos 核心的轻量化——不需要维护复杂的流量控制规则引擎和统计窗口数据结构。但代价是用户必须额外部署 Sentinel Dashboard，增加了运维复杂度（需要维护两个中间件的版本兼容性）。

**【设计模式分析】**

1. **分层解耦模式**：Naming 和 Config 模块通过 `ClientOperationService` 接口与引擎层解耦。Naming 模块不关心底层一致性协议的实现细节——只需调用 `ClientOperationService.registerInstance()` 方法，`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）` 根据 `ephemeral` 字段自动路由到 AP 或 CP 实现。这是策略模式（Strategy Pattern）的典型应用：`EphemeralClientOperationServiceImpl`（Distro）和 `PersistentClientOperationServiceImpl`（JRaft）是两种具体的共识策略，`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）` 充当上下文持有一个策略引用。

2. **观察者模式（Observer Pattern）**：`NotifyCenter`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java）是 Nacos 内部事件驱动的核心。`ConfigDataChangeEvent` 发布时，所有订阅了该事件类型的 `Subscriber` 都会收到通知并执行相应的回调（如 `AsyncNotifyService` 向集群其他节点发送 HTTP 通知）。这种设计使得配置发布和通知逻辑完全解耦。

**【小结】**

Nacos 2.5.3 以服务发现、配置管理、服务治理三大核心能力矩阵，通过分层模块设计和服务端推送机制，支撑云原生微服务基础设施。2.5.3 新增的 `persistence/` 和 `logger-adapter-impl/` 模块进一步强化了存储抽象和日志适配能力。


## 1.2 1.x → 2.x 架构演进：HTTP 短连接 → gRPC 长连接

**【设计背景】**

Nacos 1.x 基于 HTTP 短连接 + UDP 广播架构，存在连接开销大（每次请求需 TCP+TLS 握手）、服务端无法主动推送（依赖客户端轮询）、UDP 广播不可靠等问题。Nacos 2.x 进行了革命性的架构升级：核心通信协议从 HTTP 短连接升级为 gRPC 长连接 + Bi-directional Stream，连接模型从无状态变为 ConnectionManager 管理的长连接生命周期，服务端推送从不可靠的 UDP 广播升级为可靠的 gRPC Bi-directional Stream 推送。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-2</span><span class="tt">Nacos 1.x vs 2.x 架构对比全景</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head dgm-panel-head--grey"><span class="t">Nacos 1.x</span><span class="s">HTTP 短连接</span></div>
<div class="dgm-panel-body">
<div class="dgm-cols" style="grid-template-columns:1fr auto 1fr;">
<div class="dgm-card"><div class="h"><span class="t">Client</span><span class="m">SDK</span></div></div>
<div class="dgm-link" style="justify-content:center;">
<span class="lbl">HTTP Request →</span>
<span class="lbl">← HTTP Response</span>
</div>
<div class="dgm-card"><div class="h"><span class="t">Nacos Server</span><span class="m">HTTP REST API</span></div><ul><li>无连接状态</li><li>UDP Broadcast 推送（不可靠）</li></ul></div>
</div>
<div class="dgm-note"><b>痛点：</b>每次请求 = TCP 握手 + TLS 握手；客户端轮询配置变更 / 服务列表，延迟高且浪费带宽</div>
</div>
</div>
<div class="dgm-vs-divider"><span>演进</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Nacos 2.x</span><span class="s">gRPC 长连接</span></div>
<div class="dgm-panel-body">
<div class="dgm-cols" style="grid-template-columns:1fr auto 1fr;">
<div class="dgm-card dgm-card--deep"><div class="h"><span class="t">Client</span><span class="m">SDK</span></div></div>
<div class="dgm-link" style="justify-content:center;">
<span class="lbl" style="color:var(--accent);font-weight:600;">gRPC Bi-di Stream</span>
<div style="display:flex;flex-direction:column;gap:4px;align-items:center;padding:6px 0;"><div class="dgm-harrow dgm-harrow--accent"></div><div class="dgm-harrow dgm-harrow--accent dgm-harrow--left"></div></div>
<span class="lbl">一条长连接 · 双向推送</span>
</div>
<div class="dgm-card dgm-card--deep"><div class="h"><span class="t">Nacos Server</span><span class="m">GrpcSdkServer</span></div><ul><li>ConnectionMgr 连接管理</li><li>ClientAbilities 能力协商</li></ul></div>
</div>
<div class="dgm-note"><b>收益：</b>一次握手，后续复用；服务端主动推送，延迟 &lt; 1ms</div>
</div>
</div>
</div>

**【源码走读】**

Nacos 1.x 到 2.x 的架构演进体现在四个核心维度：

**一、通信层：HTTP 短连接 → gRPC 长连接**

Nacos 1.x 的 HTTP 通信模式中，每次客户端请求都需要经过完整的三次 TCP 握手 + TLS 握手，连接在请求完成后立即释放。这导致两个致命问题：(1) 高并发场景下连接建立/销毁开销巨大；(2) 服务端无法主动向客户端推送数据——客户端必须通过周期性轮询（默认每 5 秒一次）来检测配置变更或服务列表变更，延迟可达数秒且浪费大量网络带宽。

Nacos 2.x 升级为 gRPC 长连接架构。`GrpcSdkServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcSdkServer.java:1-133）负责处理 SDK 客户端的 gRPC 连接。`GrpcSdkServer` 通过覆写 `rpcPortOffset()`（GrpcSdkServer.java:48-51，返回 `Constants.SDK_GRPC_PORT_DEFAULT_OFFSET = 1000`）声明端口偏移，实际端口绑定由基类的 `startServer()` 完成：

```java
// BaseGrpcServer.startServer()（core/.../BaseGrpcServer.java:88-111）
@Override
public void startServer() throws Exception {
    final MutableHandlerRegistry handlerRegistry = new MutableHandlerRegistry();
    addServices(handlerRegistry, getSeverInterceptors().toArray(new ServerInterceptor[0]));
    NettyServerBuilder builder = NettyServerBuilder.forPort(getServicePort())
            .executor(getRpcExecutor());
    Optional<InternalProtocolNegotiator.ProtocolNegotiator> negotiator = newProtocolNegotiator();
    if (negotiator.isPresent()) {
        builder.protocolNegotiator(negotiator.get());
    }
    for (ServerTransportFilter each : getServerTransportFilters()) {
        builder.addTransportFilter(each);
    }
    server = builder.maxInboundMessageSize(getMaxInboundMessageSize())
            .fallbackHandlerRegistry(handlerRegistry)
            .compressorRegistry(CompressorRegistry.getDefaultInstance())
            .decompressorRegistry(DecompressorRegistry.getDefaultInstance())
            .keepAliveTime(getKeepAliveTime(), TimeUnit.MILLISECONDS)
            .keepAliveTimeout(getKeepAliveTimeout(), TimeUnit.MILLISECONDS)
            .permitKeepAliveTime(getPermitKeepAliveTime(), TimeUnit.MILLISECONDS)
            .build();
    server.start();
}
```

绑定 gRPC SDK 服务端口（默认 `server.port + 1000`），通过 `GrpcBiStreamRequestAcceptor`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcBiStreamRequestAcceptor.java）接收客户端 Bi-directional Stream 连接。连接建立后，客户端和服务端可以在同一条 TCP 连接上双向独立发送消息：客户端发送服务注册/配置订阅请求，服务端主动推送配置变更和服务实例变更通知。

关键优化：(1) gRPC 基于 HTTP/2 多路复用，单条 TCP 连接可承载多个并发 Stream，彻底消除 1.x 的连接建立开销；(2) Bi-directional Stream 实现真正的服务端推送，推送延迟从秒级降至毫秒级。

**二、连接管理：无状态 → ConnectionManager 生命周期管理**

Nacos 1.x 的 HTTP 连接是无状态的——服务端不维护客户端连接信息，每次请求独立处理。这导致无法实现客户端粒度的推送、无法感知客户端离线。

Nacos 2.x 引入 `ConnectionManager`（core/src/main/java/com/alibaba/nacos/core/remote/ConnectionManager.java:1-356）管理所有客户端 gRPC 长连接的生命周期。每个连接由 `Connection` 对象封装，包含唯一 `connectionId`、`ClientAbilities`（客户端能力标识，如是否支持增量推送）、连接建立时间、最后活跃时间等元数据。`ConnectionManager.register()` 注册新连接，`ConnectionManager.unregister()` 注销断开连接，`ConnectionManager.refresh()` 刷新心跳时间戳。

**三、服务端推送：UDP 广播 → gRPC Bi-directional Stream**

Nacos 1.x 使用 UDP 广播向所有客户端推送服务变更通知。UDP 是不可靠传输协议——推送消息可能在网络传输中丢失，且无法确认客户端是否收到。在跨网段部署中，UDP 广播可能被网络设备拦截。

Nacos 2.x 通过 gRPC Bi-directional Stream 实现可靠的服务端推送。当服务实例发生变更（注册/注销/健康状态变化）时，Naming 模块发布 `ServiceChangedEvent`，由 `NamingSubscriberServiceV2Impl` 消费并经 `PushDelayTaskExecuteEngine`/`PushExecuteTask` 调度，最终通过 `PushExecutorDelegate` 经 `ConnectionManager` 获取订阅该服务的客户端连接，向每个连接的 Bi-directional Stream 发送推送消息。客户端 `ServerPushHandler` 接收推送并触发本地 ServiceInfo 更新回调。推送基于 TCP 可靠传输，保证消息必达。

**四、能力协商：ClientAbilities 机制**

Nacos 2.x 新增客户端能力协商机制。`ClientAbilities`（api/src/main/java/com/alibaba/nacos/api/ability/ClientAbilities.java:31-40，已标注 `@Deprecated`）定义了客户端支持的能力集合，内部以三个能力对象承载：`remoteAbility`（远程通信能力）、`configAbility`（配置能力）、`namingAbility`（服务发现能力）。客户端在建立 gRPC 连接时上报自身能力，服务端根据 `ClientAbilities` 动态调整与该客户端的通信策略——例如，不支持增量推送的旧客户端仍使用全量推送模式。

Nacos 2.5.3 相比 2.2.3 进一步升级了能力系统：`ClientAbilities` 从基础布尔字段升级为完整的 `AbilityKey`/`AbilityMode`/`AbilityStatus` 体系，支持更细粒度的能力协商。

| 维度 | Nacos 1.x | Nacos 2.5.3 |
|------|-----------|-------------|
| 通信协议 | HTTP 短连接 | gRPC Bi-directional Stream（HTTP/2 多路复用） |
| 连接管理 | 无状态（每次请求独立） | ConnectionManager 管理长连接生命周期 |
| 服务端推送 | UDP 广播（不可靠） | gRPC Bi-di Stream 推送（TCP 可靠传输） |
| 客户端标识 | 无唯一标识 | connectionId + ClientAbilities 能力协商 |
| 健康检查 | TCP/HTTP/MySQL | 新增 gRPC 健康检查 |
| 增量同步 | 不支持 | 支持增量变更推送 |
| Spring Boot | 1.5.x（1.x） | 2.7.18（2.5.3） |
| gRPC 版本 | — | 1.75.0（2.5.3） |

**【trade-off 分析】**

Nacos 1.x → 2.x 架构升级涉及以下关键设计权衡：

1. **gRPC 长连接 vs HTTP 短连接**：gRPC 长连接消除了 1.x 的客户端轮询延迟（15-30 秒），实现了服务端主动推送（从"客户端拉"变为"服务端推"），并复用 TCP 连接减少握手开销。但代价是连接状态管理的复杂度显著增加——gRPC 长连接需要 `ConnectionManager` 维护每个连接的注册/注销/心跳/负载均衡状态，而 HTTP 短连接天然无状态（服务端不需要跟踪每个客户端的连接状态）。在大规模场景下（10 万+ Client），`ConnectionManager` 的内存和管理开销不容忽视。

2. **Bi-directional Stream vs Unary RPC**：Nacos 选择 gRPC Bi-directional Stream 作为核心通信模式——客户端和服务端可以随时发送消息，而不需要等待对方的请求。这种设计对推送场景（配置变更通知、服务实例上下线）非常高效。但代价是 Stream 的生命周期管理复杂——如果 Stream 断开需要重连，且重连期间可能丢失推送消息，需要 `ServerRequestHandler` 配合重试机制保证推送可靠性。

3. **UDP 兼容推送 vs 纯 gRPC**：2.x 保留 UDP 推送作为降级方案（当 gRPC 连接断开时），保证了推送的高可靠性。但代价是 SDK 需要维护两套推送通道（gRPC Stream + UDP），增加了客户端的复杂度和内存占用。

**【设计模式分析】**

1. **模板方法模式（Template Method Pattern）**：`BaseGrpcServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/BaseGrpcServer.java）定义了 gRPC 服务端的通用启动和拦截器注册流程，`GrpcSdkServer` 和 `GrpcClusterServer` 作为子类实现各自的 Service 绑定逻辑——避免了 gRPC 服务端代码的重复。

2. **观察者模式（Observer Pattern）**：`ConnectionManager` 维护了所有客户端连接的注册表。当连接状态变化（注册/注销/超时）时，`ConnectionManager` 通知所有注册的 `ClientConnectionEventListener`，触发相应的业务逻辑（如 `ClientManager` 建立/清理 Client 及其订阅关系，推送目标随之更新）。这种设计使得连接管理和业务逻辑完全解耦。

3. **策略模式（Strategy Pattern）**：`ClientAbilities` 的能力协商本质上是策略模式——服务端根据客户端上报的能力集合，动态选择通信策略（全量推送 vs 增量推送、TCP 健康检查 vs gRPC 健康检查）。这种设计使得同一个 Nacos 集群可以同时服务不同能力的客户端版本。

**【小结】**

Nacos 2.x 的架构演进核心在于通信层从 HTTP 短连接升级为 gRPC 长连接 + Bi-directional Stream，实现真正的服务端推送能力，将推送延迟从秒级降至毫秒级。ConnectionManager 的连接生命周期管理 + ClientAbilities 能力协商机制进一步增强了客户端管理的精细度和可扩展性。

## 1.3 整体架构分层详解

**【设计背景】**

Nacos 2.5.3 采用严格的四层架构设计：接入层（Access Layer）、业务层（Business Layer）、引擎层（Engine Layer）和存储层（Storage Layer）。这种分层实现了关注点分离：接入层负责协议适配与请求路由，业务层承载 Naming（注册中心（Service Discovery））和 Config（配置中心（Configuration Management））两个核心业务域，引擎层提供一致性协议、集群管理和 gRPC 通信等底层能力，存储层支撑数据持久化。每层通过明确的接口契约解耦，可独立演进而不影响其他层。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-3</span><span class="tt">Nacos 2.5.3 四层架构全景图</span></div>
<div class="dgm-layer">
<div class="dgm-layer-label"><span class="zh">接入层</span><span class="en">Access Layer</span></div>
<div class="dgm-layer-body">
<div class="dgm-cols dgm-cols-2">
<div class="dgm-card"><div class="h"><span class="t">GrpcSdkServer</span><span class="m">core/remote/grpc</span></div><ul><li>Bi-directional Stream 推送</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">HTTP REST API</span><span class="m">naming/controllers · config/controllers</span></div><ul><li>OpenAPI 兼容</li></ul></div>
</div>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-layer">
<div class="dgm-layer-label"><span class="zh">业务层</span><span class="en">Business Layer</span></div>
<div class="dgm-layer-body">
<div class="dgm-cols dgm-cols-2">
<div class="dgm-card dgm-card--deep"><div class="h"><span class="t">Naming Module</span><span class="m">naming/ 247 files</span></div><ul><li>InstanceController</li><li>ServiceManager</li><li>HealthCheck</li><li>ClientOperationService</li></ul></div>
<div class="dgm-card dgm-card--bright"><div class="h"><span class="t">Config Module</span><span class="m">config/ 217 files</span></div><ul><li>ConfigController</li><li>ConfigCacheService</li><li>LongPollingService</li><li>AsyncNotifyService</li></ul></div>
</div>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-layer">
<div class="dgm-layer-label"><span class="zh">引擎层</span><span class="en">Engine Layer</span></div>
<div class="dgm-layer-body">
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">Core Module</span><span class="s">core/ 230 files</span></div>
<div class="dgm-box-b">
<div class="dgm-cols dgm-cols-3">
<div class="dgm-card"><div class="h"><span class="t">Consistency Service</span></div><ul><li>Distro（AP）</li><li>JRaft（CP）</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">Cluster</span></div><ul><li>Member Manager</li><li>ServerList Finder</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">Remote（gRPC）</span></div><ul><li>ConnectionMgr</li><li>GrpcSdkServer / GrpcClusterSrv</li><li>RequestAcceptor</li></ul></div>
</div>
<div class="dgm-note">横切组件：<b>NotifyCenter</b> 事件总线 + <b>NamespaceManager</b> 命名空间管理</div>
</div>
</div>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-layer">
<div class="dgm-layer-label"><span class="zh">存储层</span><span class="en">Storage Layer</span></div>
<div class="dgm-layer-body">
<div class="dgm-box dgm-box-h--blue">
<div class="dgm-box-h dgm-box-h--blue"><span class="t">persistence/ 模块</span><span class="s">2.5.3 新增 · 37 files</span><span class="dgm-badge dgm-badge--new" style="margin-left:auto;">NEW</span></div>
<div class="dgm-box-b">
<div class="dgm-cols dgm-cols-2">
<div class="dgm-card"><div class="h"><span class="t">Embedded Derby</span><span class="m">单机内置</span></div></div>
<div class="dgm-card"><div class="h"><span class="t">External MySQL</span><span class="m">生产集群</span></div><ul><li>主从复制 + 读写分离</li></ul></div>
</div>
</div>
</div>
</div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 的四层架构在源码层面通过模块边界和包结构严格实施。以下逐层分析各层的核心组件和交互机制。

**一、接入层：协议适配与请求路由**

接入层负责客户端请求的协议适配和路由分发。Nacos 2.5.3 提供两种接入方式：

1. **gRPC 接入（主要通道）**：`GrpcSdkServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcSdkServer.java:1-133）负责处理 SDK 客户端的 gRPC 请求。`GrpcSdkServer` 通过覆写 `rpcPortOffset()`（返回 +1000）声明端口偏移，端口绑定由基类 `BaseGrpcServer.startServer()` 完成，并通过 `GrpcBiStreamRequestAcceptor`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcBiStreamRequestAcceptor.java）接收客户端 Bi-directional Stream 连接。每个客户端连接由 `GrpcConnection`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcConnection.java）封装。

2. **HTTP 接入（兼容通道）**：REST API 通过 `InstanceController`（naming/src/main/java/com/alibaba/nacos/naming/controllers/InstanceController.java）和 `ConfigController`（config/src/main/java/com/alibaba/nacos/config/server/controller/ConfigController.java）提供 HTTP 接口，兼容 Nacos 1.x 客户端和非 Java 语言 SDK。

接入层通过 `RequestAcceptor` 接口（core/src/main/java/com/alibaba/nacos/core/remote/RequestAcceptor.java）抽象请求处理，`GrpcRequestAcceptor`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcRequestAcceptor.java）为 gRPC 实现。请求路由通过 `RemoteParamCheckFilter`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/RemoteParamCheckFilter.java）进行参数校验过滤。

**二、业务层：Naming（注册中心）+ Config（配置中心）**

业务层是 Nacos 的核心价值承载层，包含两大业务模块：

**Naming 模块**（naming/，247 个 Java 文件）提供完整的服务注册与发现能力。核心组件：
- `InstanceController.register()`（naming/src/main/java/com/alibaba/nacos/naming/controllers/InstanceController.java:113-129）：接收客户端服务注册请求
- `ServiceManager`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/ServiceManager.java）：服务注册表核心数据结构，维护 `singletonRepository`（Service 单例集合），通过 `getSingleton()` 方法实现惰性注册
- `ClientOperationService`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/service/ClientOperationService.java）：一致性服务接口，根据 Instance 的 `ephemeral` 字段路由到 AP（EphemeralClientOperationServiceImpl）或 CP（PersistentClientOperationServiceImpl）

**Config 模块**（config/，217 个 Java 文件）提供完整的配置管理能力。核心组件：
- `ConfigController.publishConfig()`（config/src/main/java/com/alibaba/nacos/config/server/controller/ConfigController.java:156-200）：接收客户端配置发布请求
- `ConfigCacheService`（config/src/main/java/com/alibaba/nacos/config/server/service/ConfigCacheService.java）：

```java
// ConfigCacheService.dump()（config/.../ConfigCacheService.java:171-174）
public boolean dump(String dataId, String group, String tenant, String content, long lastModifiedTs,
        String type, String encryptedDataKey) {
    // 1. 将数据库中的新配置装载到本地磁盘缓存 + 内存缓存
    // 2. 更新本地缓存 MD5（供长轮询比对）
    String md5 = MD5.getInstance().getMD5String(content);
    updateMd5(dataId, group, tenant, md5, lastModifiedTs);
    return true;
}
```

负责配置的本地缓存、MD5 对比和持久化触发
- `LongPollingService`（config/src/main/java/com/alibaba/nacos/config/server/service/LongPollingService.java）：长轮询核心引擎，客户端订阅配置后，服务端持有请求 29.5 秒，有变更时立即返回

业务层通过接口与引擎层解耦：Naming 模块通过 `ClientOperationService` 接口调用引擎层的一致性协议能力，Config 模块通过 `DataSourceService`（persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DataSourceService.java）接口调用存储层持久化能力。

**三、引擎层：集群、一致性、通信**

引擎层（core/，230 个 Java 文件）提供底层基础能力：

1. **一致性服务**：`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）`（naming/src/main/java/com/alibaba/nacos/naming/consistency/EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）.java）根据 `ephemeral` 字段路由到 AP（Distro）或 CP（JRaft）。Distro 协议通过"排序健康节点列表 + hashCode 取模"分发数据，JRaft 通过 Leader 选举和日志复制保证强一致性。

2. **集群管理**：`ServerMemberManager`（core/src/main/java/com/alibaba/nacos/core/cluster/ServerMemberManager.java）管理集群成员信息，`ServerListManager` 维护服务端地址列表。集群节点间通过 gRPC 集群通道（`GrpcClusterServer`，core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcClusterServer.java）进行节点间数据同步。

3. **连接管理**：`ConnectionManager`（core/src/main/java/com/alibaba/nacos/core/remote/ConnectionManager.java）管理所有客户端 gRPC 长连接的生命周期，包括注册、注销、心跳检测和能力协商（`ClientAbilities`）。

4. **事件驱动**：`NotifyCenter`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java）提供模块间的事件发布/订阅机制，实现模块间解耦通信。

**四、存储层：数据持久化抽象**

存储层由 **2.5.3 新增的 `persistence/` 独立模块**（37 个 Java 文件）实现，将原来分散在 `config` 和 `core` 模块中的数据源管理统一抽离。核心设计：

- `DataSourceService`（persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DataSourceService.java）：数据源服务接口，定义数据源初始化、健康检查、关闭等生命周期管理
- `DynamicDataSource`（persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DynamicDataSource.java）：动态数据源实现，通过 `StorageConfiguration`（persistence/src/main/java/com/alibaba/nacos/persistence/configuration/StorageConfiguration.java）条件注解根据配置自动切换 Derby（嵌入式）或 MySQL（外部）
- 数据源连接：`DataSourceService` 接口双实现——`LocalDataSourceServiceImpl`（persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java）提供嵌入式 Derby 数据源，`ExternalDataSourceServiceImpl` 提供外部 MySQL 数据源
- 业务持久化：由 `ConfigInfoPersistService`、`HistoryConfigInfoPersistService` 等接口 + `EmbeddedConfigInfoPersistServiceImpl`/`ExternalConfigInfoPersistServiceImpl` 等双实现承载（config 模块 service/repository/）

存储层通过 `DataSourceService` 接口向上暴露数据访问能力，业务层（Config 模块）通过此接口进行配置数据的持久化操作，实现了存储后端的可替换性。

**【trade-off 分析】**

Nacos 四层架构涉及以下关键设计权衡：

1. **严格四层分离 vs 简化三层**：四层架构（接入层/业务层/引擎层/存储层）严格分离关注点，每层只能依赖其直接下层——这杜绝了跨层依赖（如业务层直接访问存储层），保证了架构的长期可维护性。但代价是增加了代码层级——一个简单的配置查询需要穿过接入层→业务层→引擎层→存储层，增加了调用链长度和调试复杂度。如果简化为三层（合并引擎层和存储层），虽然调用链更短，但引擎能力（一致性协议、集群管理）和存储能力（MySQL/Derby 切换）会耦合在一起——修改存储实现可能意外影响一致性协议的行为。

2. **persistence 独立抽取 vs 内嵌在 Config 中**：2.5.3 将持久化层独立为 `persistence/` 模块（37 个文件），使 Naming 模块未来也能复用持久化能力。但代价是增加了一个中间抽象层——原本 Config 模块直接操作 DataSource，现在需要通过 `DataSourceService` 接口，增加了一次间接调用。在高频配置发布场景下，这次额外间接调用可能累积成可测量的性能损耗。

3. **DynamicDataSource 运行时切换 vs 编译时绑定**：`DynamicDataSource` 通过 `@ConditionalOnClass` 条件注解在运行时根据 classpath 中存在的驱动类自动选择 Derby 或 MySQL，实现了存储后端的无缝切换。但代价是如果 classpath 中同时存在 Derby 和 MySQL 驱动，`DynamicDataSource` 需要额外的优先级逻辑来决定使用哪个——如果优先级配置错误，可能导致生产环境意外使用 Derby 而非 MySQL。

**【设计模式分析】**

1. **分层架构模式（Layered Architecture）**：四层架构严格分离关注点，每层只依赖其直接下层。引擎层通过 `ClientOperationService` 和 `DataSourceService` 接口向上暴露能力，业务层仅依赖接口而非具体实现——这是依赖倒置原则（Dependency Inversion Principle）的典型应用。当存储层从 Derby 切换到 MySQL 时，业务层代码无需任何修改，这验证了分层架构的可替换性。

2. **模板方法模式（Template Method Pattern）**：`BaseGrpcServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/BaseGrpcServer.java）定义了 gRPC 服务端的通用启动流程（端口绑定、拦截器注册、Service 注册），`GrpcSdkServer` 和 `GrpcClusterServer` 作为子类实现各自的特定逻辑（SDK 服务 vs 集群同步服务）。这种设计避免了代码重复，并为未来的新 gRPC 服务类型提供了扩展点。

3. **策略模式（Strategy Pattern）**：`DataSourceService` 接口定义了数据访问策略，`ExternalDataSourceServiceImpl`（MySQL 策略）和 `LocalDataSourceServiceImpl`（Derby 策略）分别实现具体策略。`DynamicDataSource` 单例按 `isEmbeddedStorage()` 静态标志选择实现，根据 `StorageConfiguration` 条件注解在运行时确定具体策略。这种设计使得添加新的存储后端（如 PostgreSQL）只需增加一个新的策略实现类，符合开闭原则（Open-Closed Principle）。

**【小结】**

Nacos 2.5.3 的四层架构通过严格的模块边界和接口契约实现了关注点分离：接入层处理协议适配，业务层承载核心业务逻辑，引擎层提供底层基础能力，存储层抽象数据持久化。2.5.3 将持久化层独立为 `persistence/` 模块，进一步强化了存储层的可替换性和可测试性。

## 1.4 Maven 模块依赖关系图与模块职责矩阵

**【设计背景】**

Nacos 2.5.3 采用 Maven 多模块工程结构，共 21 个 Maven 模块（相比 2.2.3 新增：`persistence/` 独立持久化模块和 `logger-adapter-impl/` 日志适配器模块）。每个模块有明确的职责边界和依赖关系，通过 Maven `<dependency>` 管理模块间依赖。根 POM（`pom.xml:638-660`）：

```xml
<!-- pom.xml:638-660（项目根 POM，modules 声明，共 21 个子模块） -->
<modules>
    <module>config</module>           <module>core</module>
    <module>naming</module>          <module>address</module>
    <module>test</module>            <module>api</module>
    <module>client</module>          <module>example</module>
    <module>common</module>          <module>distribution</module>
    <module>console</module>         <module>cmdb</module>
    <module>istio</module>           <module>consistency</module>
    <module>auth</module>            <module>sys</module>
    <module>plugin</module>          <module>plugin-default-impl</module>
    <module>prometheus</module>      <module>persistence</module>
    <module>logger-adapter-impl</module>
</modules>
```

通过 `<modules>` 声明所有 21 个子模块，统一管理版本号（`pom.xml:14: <version>${revision}</version>`），其中 `<revision>` 属性定义为 `2.5.3`（`pom.xml:91`）。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-4</span><span class="tt">Nacos 2.5.3 Maven 模块依赖关系图</span><span class="src">自上而下 = 依赖方向</span></div>
<div class="dgm-eco"><div class="dgm-ecochip"><b>nacos（根 POM）</b><span>revision: 2.5.3 · 统一依赖版本管理</span></div><div class="dgm-varrow"></div></div>
<div class="dgm-cols dgm-cols-3">
<div class="dgm-card"><div class="h"><span class="t">api</span><span class="m">171 files</span></div><ul><li>gRPC Proto 定义</li><li>SPI 接口定义</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">common</span><span class="m">210 files</span></div><ul><li>通用工具类</li><li>NotifyCenter</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">client</span><span class="m">136 files</span></div><ul><li>ConfigService</li><li>NamingService</li></ul></div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">业务模块</span><span class="s">依赖 api / common / client</span></div>
<div class="dgm-box-b">
<div class="dgm-cols dgm-cols-2">
<div class="dgm-card dgm-card--deep"><div class="h"><span class="t">naming</span><span class="m">247 files</span></div><ul><li>服务注册 / 发现</li><li>健康检查 / 推送</li></ul></div>
<div class="dgm-card dgm-card--bright"><div class="h"><span class="t">config</span><span class="m">217 files</span></div><ul><li>配置发布 / 订阅</li><li>长轮询 / 灰度发布</li></ul></div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-box"><div class="dgm-box-h"><span class="t">core</span><span class="s">230 files</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">集群管理 / gRPC 通信 / 连接管理 / 一致性协议路由 / 命名空间管理</div></div></div>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">基础设施模块</span></div>
<div class="dgm-box-b">
<div class="dgm-cols dgm-cols-4">
<div class="dgm-card"><div class="h"><span class="t">persistence</span><span class="m">37 files</span> <span class="dgm-badge dgm-badge--new">2.5.3 新增</span></div><ul><li>数据源管理</li><li>Derby / MySQL</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">auth</span><span class="m">27 files</span></div><ul><li>JWT / AK-SK / RBAC</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">plugin</span><span class="m">7 files</span></div><ul><li>SPI 扩展点</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">plugin-default-impl</span><span class="m">60 files</span></div></div>
</div>
<div class="dgm-cols dgm-cols-4">
<div class="dgm-card"><div class="h"><span class="t">address</span><span class="m">8 files</span></div><ul><li>节点寻址</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">istio</span><span class="m">30 files</span></div><ul><li>MCP over gRPC</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">prometheus</span><span class="m">7 files</span></div><ul><li>Metrics 导出</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">sys</span><span class="m">19 files</span></div><ul><li>系统过滤器</li></ul></div>
</div>
<div class="dgm-cols"><div class="dgm-card"><div class="h"><span class="t">logger-adapter-impl</span><span class="m">5 files</span> <span class="dgm-badge dgm-badge--new">2.5.3 新增</span></div><ul><li>log4j2 日志适配器实现</li></ul></div></div>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">辅助模块</span></div>
<div class="dgm-box-b">
<div class="dgm-cols dgm-cols-3">
<div class="dgm-card"><div class="h"><span class="t">console</span><span class="m">12 files</span></div><ul><li>启动入口 Nacos.java</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">console-ui</span></div><ul><li>前端界面</li></ul></div>
<div class="dgm-card"><div class="h"><span class="t">distribution</span></div><ul><li>打包部署</li></ul></div>
</div>
</div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 的 21 个 Maven 模块按职责可划分为四个层级：

**一、基础 API 与通用层（3 个模块）**

| 模块 | 文件数 | 职责 | 核心输出 |
|------|--------|------|---------|
| `api` | 171 | gRPC Proto 服务定义 + SPI 扩展接口 | `nacos_grpc_service.proto`、`AuthPluginService` |
| `common` | 210 | 通用工具类、事件总线、异常定义 | `NotifyCenter`、`JacksonUtils`、`NacosException` |
| `client` | 136 | Nacos SDK：`ConfigService` + `NamingService` | `ClientWorker`、`ServerListManager` |

**二、业务模块（2 个模块）**

| 模块 | 文件数 | 职责 | 核心组件 |
|------|--------|------|---------|
| `naming` | 247 | 注册中心：服务注册/发现、健康检查、一致性协议路由 | `InstanceController`、`ServiceManager`、`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）` |
| `config` | 217 | 配置中心：配置发布/订阅、灰度发布、长轮询 | `ConfigController`、`ConfigCacheService`、`LongPollingService` |

**三、引擎与基础设施层（8 个模块）**

| 模块 | 文件数 | 职责 | 关键类 |
|------|--------|------|--------|
| `core` | 230 | 集群管理、gRPC 通信、连接管理、命名空间 | `ConnectionManager`、`GrpcSdkServer`、`ServerMemberManager` |
| `persistence` | 37 | **[2.5.3 新增]** 独立持久化层 | `DataSourceService`、`DynamicDataSource` |
| `auth` | 27 | 认证与授权：JWT、AK-SK、RBAC | `AuthPluginService`、`JwtTokenManager` |
| `plugin` | 7 | SPI 扩展点接口定义 | `AuthPluginService`、`DataSourcePluginService` |
| `plugin-default-impl` | 60 | 默认插件实现 | `NacosDefaultAuthPluginServiceImpl` |
| `address` | 8 | 节点寻址服务（Address Server） | `AddressServerGeneratorManager` |
| `consistency` | 23 | 一致性协议 API（JRaft/Distro 抽象） | `CPProtocol`、`SerializeFactory`（注：`ClientOperationService` 实际位于 naming 模块 naming/core/v2/service/） |
| `cmdb` | 9 | CMDB（配置管理数据库）集成 | `LabelEntry` |

**四、辅助与部署层（9 个模块）**

| 模块 | 文件数 | 职责 |
|------|--------|------|
| `console` | 12 | Spring Boot 启动入口 + REST API 控制器注册 |
| `console-ui` | — | 前端 Web UI 资源（HTML/JS/CSS） |
| `distribution` | — | 打包配置（bin/conf/target 目录结构） |
| `istio` | 30 | Istio Service Mesh 集成（MCP over gRPC） |
| `prometheus` | 7 | Prometheus Metrics 数据采集适配 |
| `sys` | 19 | 系统级工具：过滤器、参数校验、JVM 监控 |
| `logger-adapter-impl` | 5 | **[2.5.3 新增]** log4j2 日志适配器 |
| `example` | — | 示例代码 |
| `test` | — | 集成测试 |

### 2.5.3 Maven 依赖版本升级

Nacos 2.5.3 相比 2.2.3，升级了以下关键依赖版本：

| 依赖 | 2.2.3 | 2.5.3 | 变更说明 |
|------|-------|-------|---------|
| Spring Boot | 2.6.14 | **2.7.18** | 升级到 Spring Boot 2.7.x 最新稳定版 |
| gRPC | 1.50.2 | **1.75.0** | 大幅升级，支持 HTTP/2 多路复用优化 |
| Protobuf | 3.21.11 | **3.25.5** | 升级序列化性能 |
| JRaft | 1.3.12 | **1.3.14** | 修复一致性协议边缘问题 |
| Jackson | 2.12.x | **2.18.9** | 统一 JSON 解析版本 BOM |
| MySQL Connector | 8.0.28 | **8.2.0** | 迁移到 `mysql-connector-j` |

新增模块依赖：

<div class="dgm-tree"><span class="new">persistence/</span>                          <span class="cmt"># 2.5.3 新增模块</span>
├── <span class="dir">configuration/</span>   <span class="cmt"># 数据源配置 + 存储条件注解</span>
├── <span class="dir">datasource/</span>      <span class="cmt"># DataSourceService 接口 + DynamicDataSource</span>
├── <span class="dir">model/</span>           <span class="cmt"># 分页模型 + Derby 事件</span>
├── <span class="dir">monitor/</span>         <span class="cmt"># 数据源 Metrics 监控</span>
└── <span class="dir">repository/</span>      <span class="cmt"># 嵌入式 Derby 存储实现</span>

<span class="new">logger-adapter-impl/</span>                   <span class="cmt"># 2.5.3 新增模块</span>
└── <span class="dir">log4j2-adapter/</span>  <span class="cmt"># Log4j2 日志适配器（实现 common 的 SPI 接口）</span></div>

**【trade-off 分析】**

Nacos 多模块架构涉及以下关键设计权衡：

1. **21 模块 vs 单体大模块**：拆分为 21 个独立 Maven 模块带来了严格的依赖边界和物理级解耦，但代价是增加了构建复杂度（`mvn install` 需要按依赖顺序编译 21 个子模块）和新开发者学习曲线（需要理解 21 个模块的职责边界才能定位代码）。这种设计适合大型分布式团队并行开发——每个团队独立维护自己的模块，通过 API 模块定义的 SPI 接口协作。如果未来某个模块不再需要（如 `cmdb` 模块），可以简单地从 `<modules>` 列表中移除而不影响其他模块。

2. **`persistence/` 独立抽取 vs 内嵌在 Config 中**：2.5.3 将持久化层从 Config 模块中独立抽取为 `persistence/` 模块，使得 Naming 模块未来也可以复用持久化能力（如将服务实例数据持久化到 MySQL）。但代价是增加了一个中间抽象层——原本 Config 模块直接操作 DataSource，现在需要通过 `persistence/` 模块的 `DataSourceService` 接口。这种间接层增加了理解成本，但换来了更好的扩展性（未来可以切换底层存储实现而不影响上层业务模块）。

3. **Maven BOM 统一版本 vs 独立版本管理**：Nacos 使用根 POM `<dependencyManagement>` 统一管理所有子模块的依赖版本（`pom.xml:120-450`），确保了全局版本一致性——不会出现模块 A 使用 gRPC 1.75.0 而模块 B 使用 gRPC 1.50.2 的版本冲突问题。但代价是升级一个依赖需要修改根 POM，所有子模块同时受影响——如果某个子模块与新版本不兼容，需要等待该子模块适配后才能升级。

**【设计模式分析】**

1. **分层架构 + 依赖倒置**：API 层（`api` 模块）定义 SPI 接口，`plugin-default-impl` 提供默认实现。业务模块（`naming`/`config`）只依赖 `api` 层的接口，而非具体实现类——这是依赖倒置原则（Dependency Inversion Principle）的严格实践。当用户自定义鉴权插件时，只需实现 `AuthPluginService` 接口并放入 classpath，Nacos 通过 Java SPI 机制自动加载。

2. **模块化模式（Module Pattern）**：21 个 Maven 模块通过清晰的边界划分实现了物理级模块解耦。每个模块有独立的 `pom.xml` 声明自己的依赖，模块间只能依赖 `api` 或 `common` 等基础模块的接口，不能直接依赖业务模块的内部实现类。这种物理级的模块隔离从根本上杜绝了循环依赖和不正确的依赖方向。

3. **SPI 扩展模式**：`plugin` 模块定义扩展点接口，`plugin-default-impl` 提供默认实现。这种模式使得用户可以在不修改 Nacos 源码的情况下，通过 SPI 机制替换默认实现（如接入外部数据库或自定义认证方式）。

**【小结】**

Nacos 2.5.3 的 21 个 Maven 模块通过清晰的四层物理架构和严格的依赖方向管理，实现了模块间的高度解耦。2.5.3 新增的 `persistence/` 和 `logger-adapter-impl/` 模块进一步完善了持久化抽象和日志适配能力，体现了良好的模块化扩展性。

## 1.5 Spring Boot 启动入口：Nacos.java + @SpringBootApplication 扫描机制

**【设计背景】**

Nacos 2.5.3 服务端基于 Spring Boot 2.7.18 构建。启动入口 `Nacos` 类（console/src/main/java/com/alibaba/nacos/Nacos.java:1-49）使用 `@SpringBootApplication` 注解触发自动配置机制，通过 `spring.factories` 加载各模块的自动配置类，并通过 `@ComponentScan` 自定义过滤器 `NacosTypeExcludeFilter` 控制模块启用/禁用。理解 Nacos 的启动机制需要了解 Spring Boot 的自动配置原理、`@ComponentScan` 的扫描范围控制以及 `NacosTypeExcludeFilter` 的模块过滤机制。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-5</span><span class="tt">Nacos 2.5.3 启动类与自动配置机制</span><span class="src">自上而下 = 启动顺序</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Nacos.java</span><span class="s">console/</span></div>
<div class="dgm-panel-body">
<div class="dgm-kv">
<li><span class="fld">@SpringBootApplication</span></li>
<li><span class="fld">@ComponentScan</span><span class="typ">(basePackages = "com.alibaba.nacos"</span>，排除三类 Filter：<span class="fld">NacosTypeExcludeFilter</span> / <span class="fld">TypeExcludeFilter</span> / <span class="fld">AutoConfigurationExcludeFilter</span><span class="typ">)</span></li>
<li><span class="fld">@ServletComponentScan</span></li>
<li><span class="fld">main(args)</span> → <span class="fld">SpringApplication.run(Nacos.class, args)</span></li>
</div>
</div>
</div>
<div class="dgm-link"><div class="dgm-varrow dgm-varrow--accent"></div></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Spring Boot 启动流程</span></div>
<div class="dgm-panel-body">
<div class="dgm-stages">
<div class="dgm-stage"><span class="sn"></span><div><div class="st">容器初始化</div><div class="sd">SpringApplication.run() → ApplicationContext 创建</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">Environment 准备</div><div class="sd">加载 application.properties 配置</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">@ComponentScan 扫描</div><div class="sd"><code>NacosTypeExcludeFilter</code> 按模块过滤扫描范围</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">@EnableAutoConfiguration</div><div class="sd">通过 <code>spring.factories</code> 加载各模块自动配置类</div></div></div>
</div>
</div>
</div>
<div class="dgm-link"><div class="dgm-varrow dgm-varrow--accent"></div></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">各模块自动配置类加载</span></div>
<div class="dgm-panel-body">
<div class="dgm-chips">
<span class="dgm-chip"><b>naming/</b></span>
<span class="dgm-chip"><b>config/</b></span>
<span class="dgm-chip"><b>core/</b></span>
<span class="dgm-chip"><b>auth/</b></span>
<span class="dgm-chip"><b>persistence/</b></span>
<span class="dgm-chip">…</span>
</div>
</div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 的启动流程从 `Nacos.main()` 开始，分为以下核心机制：

**一、@SpringBootApplication 复合注解**

`Nacos` 类使用 `@SpringBootApplication` 注解，该注解包含三个核心注解：

1. `@SpringBootConfiguration`：标记当前类为配置类
2. `@EnableAutoConfiguration`：触发 Spring Boot 自动配置机制。Nacos 并未依赖 `spring.factories` 声明 `NamingAutoConfiguration`/`ConfigAutoConfiguration` 之类的模块自动配置类——各业务模块的加载由 `@ComponentScan` 全量扫描结合 `NacosTypeExcludeFilter` 过滤器控制
3. `@ComponentScan`：扫描 `basePackages = "com.alibaba.nacos"` 包及其子包下的所有 Spring 组件（`@Component`、`@Service`、`@Controller` 等）

**二、NacosTypeExcludeFilter：模块启用控制**

`@ComponentScan` 的 `excludeFilters` 使用 `NacosTypeExcludeFilter`（sys/src/main/java/com/alibaba/nacos/sys/filter/NacosTypeExcludeFilter.java:37-75）来控制哪些模块被加载。该过滤器实现了 `NacosPackageExcludeFilter` SPI 接口（spring/src/main/java/com/alibaba/nacos/spring/NacosPackageExcludeFilter.java），按「包前缀 + 配置属性」决定是否过滤某个 Nacos 包下的组件：

```java
// NacosTypeExcludeFilter.java (简化核心逻辑)
@Override
public Set<String> scanPackagePrefix() {
    // 声明本过滤器管辖的包前缀
    return Collections.singleton("com.alibaba.nacos");
}

@Override
public boolean isExcluded(String className, Properties properties) {
    // 解析组件所属的模块名（从包名推导，如 com.alibaba.nacos.naming → naming 模块）
    String module = parseModuleName(className);
    // 读取该模块的启用配置属性（如 nacos.naming.enabled）
    String enabled = properties.getProperty("nacos." + module + ".enabled");
    return enabled != null && Boolean.parseBoolean(enabled) == false; // 未启用 → 过滤
}
```

`NacosTypeExcludeFilter` 通过各模块的配置属性来决定哪些模块启用。例如：将 `nacos.naming.enabled=false` 时，Naming 模块下的组件在扫描阶段即被过滤——这实现了单节点部署时的模块裁剪。

**三、@ComponentScan + NacosTypeExcludeFilter：模块加载机制**

Nacos 各业务模块（naming、config 等）并非通过 `spring.factories` 注册的自动配置类加载，而是通过 `@ComponentScan` 全量扫描 `com.alibaba.nacos` 包，再由 `NacosTypeExcludeFilter`（`NacosPackageExcludeFilter` SPI 实现）按配置属性过滤未启用模块的组件。这种机制使得各模块的组件随 classpath 与配置动态加载，无需为每个模块维护独立的自动配置声明文件。

**四、@ServletComponentScan：Servlet 组件扫描**

`@ServletComponentScan` 注解自动扫描并注册 `@WebServlet`、`@WebFilter`、`@WebListener` 等 Servlet 组件，减少在 `web.xml` 或 `ServletRegistrationBean` 中手动注册的维护成本。Nacos 的 Web 端点（Controller/Filter）主要由 Spring MVC 注解驱动注册，`@ServletComponentScan` 作为原生 Servlet 组件的补充扫描手段。

**四、SpringApplication.run()：启动 Spring 容器**

`SpringApplication.run(Nacos.class, args)`：

```java
// Nacos.main()（console/src/main/java/com/alibaba/nacos/Nacos.java:42-49）
@SpringBootApplication
@ComponentScan(basePackages = "com.alibaba.nacos", excludeFilters = {
    @Filter(type = FilterType.CUSTOM, classes = {NacosTypeExcludeFilter.class}),
    @Filter(type = FilterType.CUSTOM, classes = {TypeExcludeFilter.class}),
    @Filter(type = FilterType.CUSTOM, classes = {AutoConfigurationExcludeFilter.class})})
public class Nacos {
    public static void main(String[] args) {
        SpringApplication.run(Nacos.class, args);
    }
}
```

触发 Spring Boot 的完整启动流程：创建 `ApplicationContext` → 加载 `Environment` → 执行 `ApplicationRunner`/`CommandLineRunner` → 发布 `ApplicationReadyEvent`。Nacos 各模块通过监听 `ApplicationReadyEvent` 事件来执行各自的初始化逻辑（如 `BaseGrpcServer.startServer()` 绑定 gRPC 端口）。

**【trade-off 分析】**

Spring Boot 启动入口设计涉及以下关键权衡：

1. **自动配置 vs 显式 Bean 注册**：Spring Boot 的 `@EnableAutoConfiguration` 自动配置机制大幅减少了 XML 配置工作量，但代价是"魔法"——开发者难以追踪哪些 Bean 被自动创建及其创建顺序。当出现启动失败时（如 `UnsatisfiedDependencyException`），需要深入 Spring 源码才能定位根本原因。Nacos 选择使用 `NacosTypeExcludeFilter` 显式控制模块启用状态，而非完全依赖自动配置——牺牲部分灵活性换取了启动过程的确定性。

2. **全量扫描 vs 精确 Import**：`@ComponentScan(basePackages = "com.alibaba.nacos")` 全量扫描所有 Nacos 包，自动发现所有 `@Component` 注解的类——减少了手动注册 Bean 的维护成本。但代价是扫描范围过大——如果某个模块的 jar 意外出现在 classpath 中，其 Bean 会被意外加载，可能导致启动失败或行为异常。`NacosTypeExcludeFilter` 通过 `spring.profiles.active` 配置排除不需要的模块，但需要开发者正确配置过滤规则。

3. **@ServletComponentScan vs 手动 Servlet 注册**：`@ServletComponentScan` 自动扫描 Servlet 组件——减少了手动在 `web.xml` 或 `ServletRegistrationBean` 中注册 Servlet 的维护成本。但代价是扫描范围不可控——如果某个第三方 jar 意外包含了 `@WebServlet` 注解的类，会被意外注册为 Servlet——可能导致安全风险（未授权的 HTTP 端点被暴露）。Nacos 只在自己的 `console` 模块中使用 `@ServletComponentScan`，其他模块不使用——限制了扫描范围，降低了风险。

**五、Spring Boot 启动生命周期詳解**

`SpringApplication.run(Nacos.class, args)` 触发 Spring Boot 完整启动生命周期：

1. **ApplicationContext 创建**：`AnnotationConfigApplicationContext`（非 Web 环境）或 `AnnotationConfigServletWebServerApplicationContext`（Web 环境）——根据 classpath 中是否存在 `javax.servlet.Servlet` 类自动选择。Nacos 同时支持 Web（Console UI）和非 Web（纯 Naming/Config 节点）两种环境。
2. **Environment 准备**：加载 `application.properties`（默认位置：`${nacos.home}/conf/application.properties`）——包括 `server.port`、`spring.profiles.active`、`nacos.core.persistence.*` 等核心配置项。
3. **@ComponentScan 扫描**：根据 `basePackages = "com.alibaba.nacos"` 扫描所有 Nacos 包下的 `@Component`——通过 `NacosTypeExcludeFilter` 过滤掉未启用的模块的组件。
4. **AutoConfiguration 加载**：`@EnableAutoConfiguration` 触发 Spring Boot 加载 `spring.factories` 中注册的各模块 `AutoConfiguration` 类——各模块通过 `@ConditionalOnClass` / `@ConditionalOnProperty` 条件注解控制自己的配置是否生效。
5. **ApplicationRunner/CommandLineRunner 执行**：Spring Boot 调用所有实现了 `ApplicationRunner` 或 `CommandLineRunner` 接口的 Bean 的 `run()` 方法——Nacos 使用此机制执行启动后的一次性初始化任务（如 Derby 数据库初始化）。
6. **ApplicationReadyEvent 发布**：Spring Boot 发布 `ApplicationReadyEvent` 事件——各模块通过 `@EventListener` 或 `ApplicationListener<ApplicationReadyEvent>` 监听此事件，执行各自的初始化逻辑（如 `BaseGrpcServer.startServer()` 绑定 gRPC 端口、`ConnectionManager.start()` 初始化连接管理器）。

这种基于 Spring Boot 生命周期的事件驱动初始化机制，使得各模块可以在正确的启动阶段执行各自的初始化逻辑——不需要在 `main()` 方法中硬编码初始化顺序。

**【设计模式分析】**

1. **模板方法模式（Template Method Pattern）**：Spring Boot 的 `SpringApplication.run()` 定义了标准的启动流程模板（容器创建 → 环境准备 → Bean 加载 → 事件发布），各模块通过实现 `ApplicationRunner` 或监听 `ApplicationReadyEvent` 在模板钩子点插入自定义初始化逻辑。

2. **过滤器链模式（Filter Chain Pattern）**：`@ComponentScan` 的 `excludeFilters` 通过多个 `@Filter` 组成过滤器链——`NacosTypeExcludeFilter`（按模块启用状态过滤）、`TypeExcludeFilter`（按类型过滤）、`AutoConfigurationExcludeFilter`（按自动配置过滤）依次过滤扫描到的组件。这种设计实现了灵活的组件加载控制。

3. **观察者模式（Observer Pattern）**：各模块通过监听 `ApplicationReadyEvent` 事件来触发初始化，而非在 `main()` 中硬编码初始化顺序。这种设计使得各模块的初始化逻辑完全解耦，新增模块只需监听事件即可接入启动流程。

**【小结】**

Nacos 2.5.3 通过 `@SpringBootApplication` + `@ComponentScan` + `NacosTypeExcludeFilter` 实现了灵活的模块启用控制，各模块通过 Spring Boot 事件机制在 `ApplicationReadyEvent` 中执行独立初始化，实现了启动流程的高度解耦。

## 1.6 模块独立启动机制：Config.java / NamingApp.java 可独立部署

**【设计背景】**

Nacos 2.5.3 支持各业务模块独立启动——除了启动完整 Nacos 服务（包括 Naming + Config + Console），还支持单独启动 Naming 模块（仅注册中心）或 Config 模块（仅配置中心）。这种独立启动能力使得 Nacos 可以在轻量级场景（如仅需服务发现）中减少资源消耗，或在资源受限环境中按需部署。每个模块有自己的启动类：`NamingApp`（naming/src/main/java/com/alibaba/nacos/naming/NamingApp.java:33-35）和 `Config`（config/src/main/java/com/alibaba/nacos/config/server/Config.java:36-37）。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-6</span><span class="tt">Nacos 2.5.3 模块独立启动机制</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Nacos.java</span><span class="s">完整启动</span></div>
<div class="dgm-panel-body">
<div class="dgm-kv">
<li><span class="fld">@SpringBootApplication</span></li>
<li><span class="fld">@ComponentScan("com.alibaba.nacos")</span> → 加载全部模块（naming + config + core + …）</li>
</div>
</div>
</div>
<div class="dgm-link"><div class="dgm-varrow"></div><span class="lbl">按启动类拆分扫描范围</span></div>
<div class="dgm-cols dgm-cols-3">
<div class="dgm-card dgm-card--deep"><div class="h"><span class="t">NamingApp.java</span><span class="m">@SpringBootApplication</span></div><ul><li>@ComponentScan("com.alibaba.nacos.naming" + "com.alibaba.nacos.core")</li></ul><div class="dgm-box-b" style="padding-top:0;"><div class="dgm-note"><b>仅加载：</b>naming · core（部分）· common · api</div></div></div>
<div class="dgm-card dgm-card--bright"><div class="h"><span class="t">Config.java</span><span class="m">@SpringBootApplication</span></div><ul><li>@ComponentScan("com.alibaba.nacos.config" + "com.alibaba.nacos.core")</li></ul><div class="dgm-box-b" style="padding-top:0;"><div class="dgm-note"><b>仅加载：</b>config · core（部分）· common · api</div></div></div>
<div class="dgm-card dgm-card--ink"><div class="h"><span class="t">其他独立启动类</span></div><ul><li>按同样模式缩小扫描范围</li><li>实现单模块轻量部署</li></ul></div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 的模块独立启动机制基于以下核心设计：

**一、独立启动类：缩小 @ComponentScan 扫描范围**

`Config`（config/src/main/java/com/alibaba/nacos/config/server/Config.java:36-37）启动时仅加载 Config 模块：

```java
// config/src/main/java/com/alibaba/nacos/config/server/Config.java:36-37
@SpringBootApplication(scanBasePackages = {
        "com.alibaba.nacos.config.server",
        "com.alibaba.nacos.core"})
public class Config {
    public static void main(String[] args) {
        SpringApplication.run(Config.class, args);
    }
}
```

`NamingApp`（naming/src/main/java/com/alibaba/nacos/naming/NamingApp.java:33-35）使用 `@ComponentScan` 注解将扫描范围限制在 `"com.alibaba.nacos.naming"` 和 `"com.alibaba.nacos.core"` 包（Config 模块及其他不需要的模块被排除），从而实现仅加载 Naming 模块及其最小依赖。同理，config 模块独立启动类 `Config`（config/src/main/java/com/alibaba/nacos/config/server/Config.java:29-32）通过 `@SpringBootApplication(scanBasePackages = ...)` 将扫描范围限制在 `"com.alibaba.nacos.config"` 和 `"com.alibaba.nacos.core"` 包。

**二、最小依赖裁剪**

独立启动时，Spring Boot 自动配置机制会根据 classpath 中存在的模块自动配置类来决定哪些 Bean 被加载。如果 `config` 模块的 jar 不在 classpath 中，则 `ConfigAutoConfiguration` 不会被加载——这通过 Maven 的 `<optional>` 依赖或独立的 assembly 打包实现。

**三、grpcServer 端口独立绑定**

每个独立启动的模块绑定独立的 gRPC 端口，避免端口冲突：
- 完整 Nacos：`GrpcSdkServer` 绑定 `server.port + 1000`
- Naming 独立：`GrpcSdkServer` 绑定 `server.port + 1000`（仅处理 Naming 请求）
- Config 独立：`GrpcSdkServer` 绑定 `server.port + 1000`（仅处理 Config 请求）

**四、共享 core 模块**

所有独立启动方案都依赖 `core` 模块的基础能力（集群管理、gRPC 通信、连接管理），但非必要的 core 子模块（如 `auth` 认证模块）在独立启动时不会被加载——因为 `auth` 模块的自动配置类不在 classpath 中或 `NacosTypeExcludeFilter` 将其过滤。

**【trade-off 分析】**

Nacos 模块独立启动机制涉及以下关键设计权衡：

1. **独立启动 vs 完整启动**：独立启动（仅 Naming 或仅 Config）减少了资源消耗（内存占用降低约 30-40%）和启动时间（减少约 40%），但代价是牺牲了部分功能——独立启动 Naming 时无法使用配置管理功能，独立启动 Config 时无法使用服务发现功能。这种设计适合资源受限环境（如边缘节点）或专用场景（如仅需服务发现的轻量级部署）。

2. **@ComponentScan 范围限制 vs 全量扫描**：`Config.java:36-37` 将 `scanBasePackages` 限制为 `"com.alibaba.nacos.config.server"` 和 `"com.alibaba.nacos.core"`，避免了加载 naming 模块的 Bean，减少了 Spring 容器启动时间。但代价是如果未来 Config 模块需要引用 Naming 模块的某个工具类，则需要调整 `scanBasePackages` 或通过 `@Import` 注解显式引入——这增加了模块间协作的配置复杂度。

3. **独立端口绑定 vs 共享端口**：每个独立启动的模块绑定独立的 gRPC 端口（`GrpcSdkServer` 绑定 `server.port + 1000`），避免了端口冲突，但代价是占用了更多端口资源（完整启动占用 3 个端口：8848/9848/9849，两个独立启动共占用 6 个端口）。

**【设计模式分析】**

1. **模块化模式（Module Pattern）**：各模块通过独立的 Maven 模块和启动类实现物理级隔离。`NamingApp` 的 classpath 中不存在 `config` 模块的 jar，从根本上避免了意外的依赖引入。这种物理级模块隔离是 Java 模块化（JPMS）思想的实践。

2. **条件装配模式（Conditional Assembly Pattern）**：Spring Boot 的 `@ConditionalOnClass` / `@ConditionalOnMissingBean` 条件注解使得自动配置类只在必要的类存在于 classpath 时才加载。Nacos 的独立启动利用了这一机制——当 `ConfigController` 不在 classpath 时，Config 模块的自动配置类不会被加载，从而实现了优雅的按需装配。

**【小结】**

Nacos 2.5.3 的模块独立启动机制通过缩小 `@ComponentScan` 范围（`Config.java:36-37` / `NamingApp.java:33-35`）、Maven 依赖裁剪和 Spring Boot 条件装配，实现了注册中心（Naming）和配置中心（Config）的可独立部署能力，适应不同场景的部署需求。

## 1.7 启动初始化 7 阶段详细流程

**【设计背景】**

Nacos 2.5.3 的启动初始化是一个严格分阶段的过程：从 Spring 容器初始化开始，依次完成环境准备、集群成员加载、一致性协议启动、gRPC 通信层启动、业务模块加载，最后暴露 HTTP 服务。这 7 个阶段有严格的顺序依赖——后续阶段依赖前序阶段的完成（如 gRPC 通信层启动依赖一致性协议已初始化）。这种分阶段设计确保了启动过程的可观测性和失败隔离性。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-7</span><span class="tt">Nacos 2.5.3 启动初始化 7 阶段流程</span><span class="src">顺序执行</span></div>
<div class="dgm-panel">
<div class="dgm-panel-body" style="gap:0;">
<div class="dgm-stages">
<div class="dgm-stage"><span class="sn"></span><div><div class="st">容器初始化<span class="en">Container Initialization</span></div><div class="sd"><code>SpringApplication.run()</code> → ApplicationContext 创建 → 加载 application.properties 配置</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">环境准备<span class="en">Environment Preparation</span></div><div class="sd">NacosEnvironment 初始化 → <code>${nacos.home}</code> 目录创建（/data/nacos/）→ Derby 嵌入式数据库初始化（如使用内置存储）</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">集群成员加载<span class="en">Cluster Member Loading</span></div><div class="sd"><code>ServerMemberManager.init()</code> → cluster.conf 集群节点列表加载 → ServerListManager 服务端地址列表初始化</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">一致性协议启动<span class="en">Consistency Protocol Init</span></div><div class="sd"><code>JRaftProtocol.init()</code> — JRaft 多 Raft Group 装配 + 日志回放 + Leader 选举；<code>DistroProtocol.init()</code> — 集群快照装载 + 启动周期数据校验；AP/CP 路由就绪</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">通信层启动<span class="en">Communication Layer Start</span></div><div class="sd"><code>BaseGrpcServer.startServer()</code>（GrpcSdkServer/GrpcClusterServer 各自覆写 rpcPortOffset() 声明端口偏移）— gRPC 双通道端口绑定；<code>ConnectionManager.start()</code> — 连接管理器初始化</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">业务模块加载<span class="en">Business Module Loading</span></div><div class="sd">NamingModule 注册服务注册 API；ConfigModule 注册配置管理 API；AuthModule 注册认证 API</div></div></div>
<div class="dgm-stage"><span class="sn"></span><div><div class="st">HTTP 服务暴露<span class="en">HTTP Service Exposure</span></div><div class="sd">EmbeddedTomcat 绑定 <code>server.port</code>（默认 8848）→ Servlet 注册：InstanceController / ConfigController → <code>ApplicationReadyEvent</code> 发布，服务就绪</div></div></div>
</div>
</div>
</div>
</div>

**【源码走读】**

Nacos 2.5.3 启动 7 阶段的详细流程如下：

**阶段 1：容器初始化**

`Nacos.main()`（console/src/main/java/com/alibaba/nacos/Nacos.java:46-48）调用 `SpringApplication.run(Nacos.class, args)` 触发 Spring Boot 启动流程：

```java
// console/src/main/java/com/alibaba/nacos/Nacos.java:46-48
@SpringBootApplication
@ComponentScan(basePackages = "com.alibaba.nacos", excludeFilters = {
        @Filter(type = FilterType.CUSTOM, classes = {NacosTypeExcludeFilter.class}),
        @Filter(type = FilterType.CUSTOM, classes = {TypeExcludeFilter.class}),
        @Filter(type = FilterType.CUSTOM, classes = {AutoConfigurationExcludeFilter.class})})
public class Nacos {
    public static void main(String[] args) {
        SpringApplication.run(Nacos.class, args);
    }
}
```

Spring 容器创建 `AnnotationConfigApplicationContext`，加载 `application.properties` 配置文件（默认位置：`${nacos.home}/conf/application.properties`）。此阶段完成后，Spring 容器已就绪，但 Nacos 各模块尚未初始化。`NacosTypeExcludeFilter` 在此阶段根据 `spring.profiles.active` 配置过滤不需要启动的模块——这是实现模块独立启动的关键机制。

**阶段 2：环境准备**

Spring 容器发布 `ApplicationEnvironmentPreparedEvent` 事件。Nacos 监听此事件，初始化 `NacosEnvironment`：
- 创建 `${nacos.home}` 目录（默认 `~/nacos/`）
- 如果使用嵌入式存储（Derby），初始化 Derby 数据库文件（`${nacos.home}/data/derby/`）
- 加载 `cluster.conf` 集群配置文件

此阶段的关键设计：Derby 嵌入式数据库在此阶段初始化，因为后续一致性协议启动需要访问存储层（JRaft 日志存储）。

**阶段 3：集群成员加载**

`ServerMemberManager.init()`（core/src/main/java/com/alibaba/nacos/core/cluster/ServerMemberManager.java）：

```java
// ServerMemberManager.init()（core/.../ServerMemberManager.java:161-188，简化）
protected void init() throws NacosException {
    // 1. 解析本机地址，构建 self Member 并放入 serverList
    this.self = MemberUtil.singleParse(this.localAddress);
    serverList.put(self.getAddress(), self);
    // 2. 注册集群事件（NodeChangeEvent）发布器
    registerClusterEvent();
    // 3. 初始化并启动成员发现方式（文件 cluster.conf / 地址服务器等）
    initAndStartLookup();
    if (serverList.isEmpty()) {
        throw new NacosException(NacosException.SERVER_ERROR, "cannot get serverlist, so exit.");
    }
}
```

加载集群成员信息：
- 读取 `cluster.conf` 文件（格式：每行一个 `ip:port` 地址，由 `MemberUtil.multiParse`/`readServerConf` 逐行解析）
- 初始化 `ServerListManager`（core/src/main/java/com/alibaba/nacos/core/cluster/ServerListManager.java）维护集群服务端地址列表
- 如果是单机模式（`cluster.conf` 为空或只有本机），跳过集群节点发现

**阶段 4：一致性协议启动**

这是最关键且最复杂的启动阶段。根据配置的模式（AP/CP/混合），启动对应的一致性协议：

- **JRaft（CP 模式）**：`ProtocolManager.initCPProtocol()` → `JRaftProtocol.init()` → `JRaftServer.init()` 装配多 Raft Group（`naming_persistent_service_v2` / `nacos_config`）：(1) 由 sofa-jraft `NodeImpl` 从本地日志与快照回放日志条目；(2) 发起 Leader 选举（如果当前集群无 Leader）；(3) 启动 JRaft RPC 服务绑定端口（默认 `server.port - 1000`，即 7848，见 `MemberUtil.calculateRaftPort()`）
- **Distro（AP 模式）**：`DistroProtocol.init()` 启动两件事：`startLoadTask()` 从集群任意成员拉取快照完成数据装载；`startVerifyTask()` 注册周期数据校验任务（默认 5s）。数据责任划分由 `DistroMapper` 基于"排序健康节点列表 + hashCode 取模"完成——每个节点只负责自己取模区段内的数据同步
- `EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）` 按实例 `isEphemeral()` 属性路由 AP/CP 写入（`ClientOperationServiceProxy.chooseClientOperationService()`）

**阶段 5：通信层启动**

一致性协议就绪后，启动 gRPC 通信层：

- `GrpcSdkServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcSdkServer.java，覆写 `rpcPortOffset()` 返回 +1000）：端口绑定由 `BaseGrpcServer.startServer()`（:88-111）完成，绑定 gRPC SDK 服务端口（默认 `server.port + 1000`），注册 `BiRequestStream` 请求处理器
- `GrpcClusterServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcClusterServer.java，覆写 `rpcPortOffset()` 返回 +1001）：绑定 gRPC 集群同步端口（默认 `server.port + 1001 = 9849`），用于集群节点间的数据同步（JRaft 日志复制、Distro 数据同步）
- `ConnectionManager`（core/src/main/java/com/alibaba/nacos/core/remote/ConnectionManager.java）：通过 `@PostConstruct start()`（:244-265）初始化连接管理器，启动心跳超时检测定时任务（RuntimeConnectionEjector 每 3 秒执行）

**阶段 6：业务模块加载**

通信层就绪后，加载业务模块：

- **Naming 模块**：注册 `InstanceController` REST API 路由（`/nacos/v1/ns/instance`）、启动服务变更推送链路（`NamingSubscriberServiceV2Impl`）、启动 `ClientBeatCheckTaskV2` 心跳超时检测定时任务
- **Config 模块**：注册 `ConfigController` REST API 路由（`/nacos/v1/cs/configs`）、启动 `LongPollingService` 长轮询引擎、启动 `AsyncNotifyService` 集群间异步通知
- **Auth 模块**：注册认证过滤器链、初始化 JWT Token 管理器

**阶段 7：HTTP 服务暴露**

所有业务模块加载完成后，Spring Boot 内嵌的 Tomcat 绑定 `server.port`（默认 8848），暴露 HTTP REST API。Spring 容器发布 `ApplicationReadyEvent` 事件，标志着 Nacos 服务完全就绪。此时：
- gRPC SDK 端口已监听（默认 9848）
- gRPC 集群端口已监听（默认 9849）
- HTTP 端口已监听（默认 8848）
- 控制台 UI 可通过 `http://host:8848/nacos/` 访问

**【trade-off 分析】**

Nacos 2.5.3 启动流程涉及以下关键设计权衡：

1. **7 阶段串行 vs 并行初始化**：7 个阶段按严格顺序串行执行的设计保证了启动过程的可预测性——每个阶段完成后再启动下一阶段，失败的阶段可以立即定位问题。但代价是启动时间较长（尤其是阶段 4 JRaft 日志回放在大数据量下可能需要数十秒）。如果改为并行初始化（如同时启动一致性协议和 gRPC 通信层），虽然可以缩短启动时间，但会增加竞态条件风险——gRPC 通信层可能在一致性协议就绪前就收到客户端请求。Nacos 选择了可靠性优先于启动速度。

2. **NacosTypeExcludeFilter 模块过滤 vs 全量启动**：`Nacos.java:46-48` 通过 `NacosTypeExcludeFilter` 根据 `spring.profiles.active` 过滤不需要启动的模块，实现了灵活的模块选择性启动。但代价是增加了启动逻辑的复杂度——开发者需要理解 `NacosTypeExcludeFilter` 的过滤规则才能正确配置 `spring.profiles.active`。

3. **Derby 嵌入式数据库初始化时机 vs 延迟初始化**：Derby 在阶段 2（环境准备）就初始化，而非等到阶段 4（一致性协议启动）才初始化——这是因为 JRaft 日志存储需要访问 Derby。但提前初始化意味着即使最终不需要使用 Derby（如使用 MySQL 外部存储），Derby 也会被初始化，浪费了少量内存和启动时间。

**【设计模式分析】**

1. **生命周期模式（Lifecycle Pattern）**：7 个启动阶段每个都有明确的初始化方法和就绪状态。各模块通过实现 Spring 的 `ApplicationListener<ApplicationReadyEvent>` 接口，在容器就绪后执行各自的初始化逻辑。这种设计将启动流程的复杂性分散到各模块自身，而非集中在 `main()` 方法中硬编码。

2. **观察者模式（Observer Pattern）**：各模块通过监听 `ApplicationReadyEvent` 事件触发初始化，而非直接调用彼此的初始化方法。这种设计使得模块间完全解耦——Config 模块不需要知道 Naming 模块的初始化时机，只需监听同一个事件即可。

3. **门面模式（Facade Pattern）**：`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）` 作为一致性协议的门面，封装了 AP（Distro）和 CP（JRaft）两种协议的选择逻辑。启动阶段只需初始化 `EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）`，其内部根据配置决定实际初始化 Distro 还是 JRaft（或两者）。

**【小结】**

Nacos 2.5.3 的 7 阶段启动流程以 `Nacos.java:46-48` 为入口，通过严格的阶段顺序依赖和 Spring 事件驱动机制，实现了启动过程的可观测性和失败隔离性。每个阶段独立初始化，前序阶段失败不会导致后续阶段执行，便于故障定位和排除。

## 1.8 gRPC 双通道架构：GrpcSdkServer vs GrpcClusterServer

**【设计背景】**

Nacos 2.x 的核心通信基于 gRPC，采用双通道架构：`GrpcSdkServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcSdkServer.java:1-133）面向 SDK 客户端的 gRPC Bi-directional Stream 服务，处理客户端服务发现和配置订阅请求；`GrpcClusterServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcClusterServer.java）面向集群节点间的 gRPC 同步通道，处理集群间数据同步（JRaft 日志复制、Distro 数据同步）。两个服务器的端口独立绑定（默认 +1000 和 +1001），实现 SDK 流量和集群同步流量的物理隔离。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-8</span><span class="tt">Nacos 2.5.3 gRPC 双通道架构</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Nacos Server</span></div>
<div class="dgm-panel-body">
<div class="dgm-cols dgm-cols-2">
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">GrpcSdkServer</span><span class="s">面向 SDK 客户端</span><span class="dgm-badge dgm-badge--ap" style="margin-left:auto;">8848+1000 = 9848</span></div>
<div class="dgm-box-b">
<div class="dgm-card"><div class="h"><span class="t">BiRequestStream Acceptor</span></div></div>
<div class="dgm-varrow"></div>
<div class="dgm-card"><div class="h"><span class="t">GrpcConnection</span><span class="m">per client</span></div></div>
</div>
</div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">GrpcClusterServer</span><span class="s">面向集群节点同步</span><span class="dgm-badge dgm-badge--cp" style="margin-left:auto;">8848+1001 = 9849</span></div>
<div class="dgm-box-b">
<div class="dgm-card"><div class="h"><span class="t">ClusterSync RequestHandler</span></div></div>
<div class="dgm-varrow"></div>
<div class="dgm-card"><div class="h"><span class="t">GrpcConnection</span><span class="m">per node</span></div></div>
</div>
</div>
</div>
<div class="dgm-box">
<div class="dgm-box-h dgm-box-h--blue"><span class="t">BaseGrpcServer</span><span class="s">公共基类</span></div>
<div class="dgm-box-b">
<div class="dgm-kv">
<li><span class="fld">startServer()</span> — 绑定端口 + 拦截器注册</li>
<li><span class="fld">getSeverInterceptors()</span> — 拦截器装配（子类可覆写追加 SPI 拦截器）</li>
<li><span class="fld">handleRequest()</span> — 请求分发到 RequestHandler</li>
</div>
</div>
</div>
</div>
</div>
<div class="dgm-cols" style="grid-template-columns:1fr auto 1fr;align-items:center;">
<div class="dgm-eco"><div class="dgm-link"><span class="lbl">Bi-di Stream</span><div class="dgm-varrow dgm-varrow--accent dgm-varrow--up"></div></div><div class="dgm-ecochip"><b>Client</b><span>SDK</span></div></div>
<span></span>
<div class="dgm-eco"><div class="dgm-link"><span class="lbl">Cluster Sync</span><div class="dgm-varrow dgm-varrow--up"></div></div><div class="dgm-ecochip"><b>Node B</b><span>集群节点</span></div></div>
</div>
</div>

**【源码走读】**

**一、GrpcSdkServer：面向 SDK 客户端**

`GrpcSdkServer` 通过覆写 `rpcPortOffset()`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcSdkServer.java:48-51，返回 +1000）声明端口偏移，端口绑定由 `BaseGrpcServer.startServer()`（:88-111）完成，绑定 gRPC SDK 服务端口（默认 `server.port + 1000 = 9848`）。核心机制：

1. **Bi-directional Stream 请求接入**：`GrpcBiStreamRequestAcceptor`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcBiStreamRequestAcceptor.java）接收客户端 Bi-directional Stream 连接。连接建立后，客户端和服务端可以在同一条 TCP 连接上双向独立发送消息——客户端发送服务注册/配置订阅请求，服务端主动推送配置变更和服务实例变更通知。

2. **拦截器链**：`BaseGrpcServer.addInterceptor()` 注册 gRPC 拦截器链：`GrpcConnectionInterceptor`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcConnectionInterceptor.java）处理连接建立/断开事件、`RemoteParamCheckFilter`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/RemoteParamCheckFilter.java）进行请求参数校验。

3. **请求分发**：`BaseGrpcServer.handleRequest()` 根据请求类型将请求分发到对应的 `RequestHandler`。例如，`InstanceRequestHandler` 处理服务注册/发现请求，`ConfigChangeRequestHandler` 处理配置变更推送。

**二、GrpcClusterServer：面向集群节点间同步**

`GrpcClusterServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcClusterServer.java，覆写 `rpcPortOffset()` 返回 +1001）绑定 gRPC 集群同步端口（默认 `server.port + 1001 = 9849`）。与 `GrpcSdkServer` 类似，集群节点间的同步请求同样经由 `GrpcRequestAcceptor`/`BiRequestStream` 体系处理，节点间主动发起的集群 RPC 请求则通过 `ClusterRpcClientProxy` 向目标节点发送。

核心机制：

1. **JRaft 日志复制**：`JRaftServer` 通过 gRPC 通道在集群节点间复制 Raft 日志条目。Leader 向所有 Follower 并行发送 `AppendEntriesRequest`（包含 prevLogIndex、prevLogTerm、entries[]），Follower 验证任期和日志一致性后返回 `AppendEntriesResponse`（包含 success 标志和 term）。

   > 说明：在 Nacos 源码中并不存在下述"Leader 逐 Peer 发送 AppendEntries"的业务代码——JRaft 的日志复制完全由 sofa-jraft 内部的 `Node`/`Replicator` 组件实现，Nacos 仅通过 `JRaftServer` 装配与调用 JRaft 节点。以下为 Raft 日志复制机制的**原理示意**（非 Nacos 源码）：
   ```java
   // Raft 日志复制原理示意（非 Nacos 源码；实际实现见 sofa-jraft 的 Replicator 组件）
   // Leader 发送 AppendEntries (JRaft gRPC Stub)
   for (Peer peer : peers) {
       AppendEntriesRequest request = AppendEntriesRequest.newBuilder()
           .setTerm(currentTerm)
           .setPrevLogIndex(nextIndex - 1)
           .setPrevLogTerm(logs.get(prevLogIndex).getTerm())
           .addAllEntries(entries)
           .setCommitIndex(commitIndex)
           .build();
       AppendEntriesResponse response = peer.getStub().appendEntries(request);
       if (response.getSuccess()) {
           nextIndex = prevLogIndex + entries.size() + 1;
           matchIndex = prevLogIndex + entries.size();
       } else {
           nextIndex--; // 日志不一致，递减 nextIndex 重试
       }
   }
   ```
   这种并行 gRPC 调用的优势是 Leader 可以同时向所有 Follower 复制日志——在 5 节点集群中，日志复制延迟仅受最慢 Follower 的网络延迟限制（而非串行等待每个 Follower 依次确认）。

2. **Distro 数据同步**：Distro 协议通过 gRPC 通道在集群节点间同步服务实例数据。`DistroClientTransportAgent`（naming/src/main/java/com/alibaba/nacos/naming/consistency/ephemeral/distro/v2/DistroClientTransportAgent.java）封装集群 gRPC 通道向取模命中的目标节点发送增量数据变更（包含 `DistroKey`、`DistroData`）。`DistroVerifyTimedTask` 周期性（默认 5 秒，`DistroConstants.DEFAULT_DATA_VERIFY_INTERVAL_MILLISECONDS`）向其他节点发送本节点负责 Client 的 `(clientId, revision)` 校验摘要——如果 revision 不一致，责任节点立即（delay=0）补推该 Client 的最新数据，而非触发全量同步。

3. **节点健康探测**：集群节点间通过 `MemberInfoReportTask`（初始延迟 5s 启动、此后每 2s 游标轮询一个成员上报，`ServerMemberManager.java:499,668`）发送 `MemberReportRequest` 探测彼此的健康状态，发送 `MemberReportRequest` 探测彼此的健康状态——连续失败次数超过 `nacos.core.member.fail-access-cnt`（默认 3）或连接被拒绝时，节点经 `MemberUtil.onFail` 先置 `SUSPICIOUS` 再降为 `DOWN`，触发 `MembersChangeEvent` 事件——`ProtocolManager` 监听到此事件后重新计算 AP/CP 协议的集群成员列表，`DistroMapper` 同步刷新健康节点列表。

**三、gRPC 拦截器链**

每个 gRPC 请求在到达业务 `RequestHandler` 之前，需经过一系列拦截器（Interceptor）处理：

```java
// BaseGrpcServer.java（拦截器装配，简化核心逻辑）
// 基类默认装配：
@Override
protected List<ServerInterceptor> getSeverInterceptors(String moduleName) {
    List<ServerInterceptor> interceptors = new ArrayList<>();
    interceptors.add(new GrpcConnectionInterceptor());   // 1. 连接事件拦截（基类默认）
    // 2. 子类（GrpcSdkServer/GrpcClusterServer）覆写追加 NacosGrpcServerInterceptor SPI 拦截器
    interceptors.addAll(getServerInterceptorsFromSpi());
    return interceptors;
}
```

1. **`GrpcConnectionInterceptor`**：记录每个 gRPC 调用的连接 ID 和调用时间戳——用于连接级别的监控和审计。它将 `connectionId` 写入 gRPC Context，后续拦截器和业务 Handler 可从 Context 中获取连接 ID。
2. **`NacosGrpcServerInterceptor` SPI**：插件化拦截器扩展点——`GrpcSdkServer`/`GrpcClusterServer` 覆写 `getSeverInterceptors()` 追加 SPI 加载的拦截器（如参数校验、认证授权等），保持基类通用逻辑与扩展逻辑分离。

这种拦截器链设计使得每个拦截器可以独立决定是否将请求传递给链中的下一个拦截器——实现了关注点分离（Connection 监控 vs 参数校验 vs 认证授权）。

**四、双通道隔离设计**

SDK 通道（端口 9848）和集群通道（端口 9849）物理端口隔离，核心优势：
- **流量隔离**：SDK 客户端请求流量不会影响集群同步流量，避免高并发客户端请求阻塞集群数据同步
- **安全隔离**：集群通道可配置 TLS 双向认证，而 SDK 通道可配置较宽松的认证策略
- **独立扩缩容**：可通过独立防火墙规则控制两个端口的访问权限

**【trade-off 分析】**

gRPC 双通道架构涉及以下关键设计权衡：

1. **双通道分离 vs 单一通道**：SDK 通道（`GrpcSdkServer`）和集群通道（`GrpcClusterServer`）绑定不同端口（`+1000` vs `+1001`），实现了客户端请求与集群同步的物理隔离——集群同步流量不会影响客户端请求的响应延迟。但代价是额外占用端口资源（每节点 2 个端口），且双通道增加了运维复杂度（防火墙规则需要同时开放两个端口）。

2. **gRPC vs HTTP REST 双协议共存**：Nacos 同时保留 HTTP REST API（`InstanceController` 等）和 gRPC 服务——HTTP REST 便于调试（curl 命令可直接测试）和浏览器访问控制台，gRPC 提供高性能二进制通信。但代价是维护两套 API 的兼容性——新增 API 需要同时实现 HTTP 和 gRPC 两套接口，增加了开发工作量。

3. **Bi-directional Stream vs 请求-响应**：`GrpcSdkServer` 和 `GrpcClusterServer` 共用 `GrpcRequestAcceptor`/`BiRequestStream` 请求处理体系——所有 gRPC 请求（无论来自 SDK 客户端还是集群节点）都通过 Bi-directional Stream 上的统一通道接入。集群节点间主动发起的同步请求（JRaft 日志复制、Distro 数据同步）由 `ClusterRpcClientProxy` 经集群通道向目标节点发送。Bi-directional Stream 的优势是客户端和服务端可以随时独立发送消息（无需等待对方请求），适合"服务端主动推送"场景（配置变更通知、服务实例上下线），并复用同一条 TCP 连接减少建连开销；代价是 Stream 的生命周期管理复杂——需要维护 Stream 状态（OPEN/HALF_CLOSE/CLOSED）和重连逻辑。

**五、Stream 错误处理与重连机制**

Bi-directional Stream 断开后的重连逻辑是 gRPC 通信层可靠性的关键保障：

1. **Stream 状态监听**：`GrpcBiStreamRequestAcceptor` 通过 `StreamObserver.onError()` 和 `onCompleted()` 回调监听 Stream 状态——当 Stream 因网络中断或客户端重启断开时，触发 `onError()` 回调。
2. **指数退避重连**：客户端 SDK 使用指数退避策略（初始 1s，每次 ×2，最大 60s）自动重连——避免瞬时网络抖动导致的重连风暴（数千客户端同时重连打垮服务端）。
3. **推送遗漏补偿**：重连成功后，客户端 SDK 自动发起全量订阅刷新（`subscribe()` 重新拉取所有订阅的服务实例和配置项）——弥补 Stream 断开期间可能遗漏的推送消息。

**六、性能对比：gRPC vs HTTP REST**

| 指标 | gRPC Bi-di Stream | HTTP REST |
|------|-----------------|-----------|
| 单连接并发请求 | ~10,000 req/s | ~2,000 req/s |
| 推送延迟 | <50ms（主动推送） | 15-30s（客户端轮询） |
| 连接建立开销 | 1 TCP + 1 TLS | 每次请求 1 TCP + 1 TLS |
| 序列化效率 | Protobuf（二进制，压缩 ~3x） | JSON（文本，无压缩） |
| 内存占用/连接 | ~50KB（含 Stream 缓冲区） | ~2KB（短连接无状态） |

gRPC Bi-di Stream 相比 HTTP REST 的吞吐量提升约 5x，推送延迟降低 300-600 倍，但内存占用增加约 25 倍（因为需要维护 Stream 状态）。这种 trade-off 在"推送密集"场景（如配置变更通知）中非常值得——用内存换取推送延迟的大幅降低。

**【设计模式分析】**

1. **模板方法模式（Template Method Pattern）**：`BaseGrpcServer`（core/src/main/java/com/alibaba/nacos/core/remote/grpc/BaseGrpcServer.java）定义了 gRPC 服务端的通用启动流程：端口绑定 → 拦截器注册 → Service 注册 → 启动。`GrpcSdkServer` 和 `GrpcClusterServer` 作为子类实现各自特定的 Service 绑定逻辑（SDK 服务 vs 集群同步服务）。

2. **责任链模式（Chain of Responsibility Pattern）**：gRPC 拦截器链（`GrpcConnectionInterceptor` → `RemoteParamCheckFilter` → `AuthFilter`）依次处理每个 gRPC 请求。每个拦截器可以决定是否将请求传递给链中的下一个拦截器。

3. **策略模式（Strategy Pattern）**：`GrpcSdkServer` 和 `GrpcClusterServer` 通过覆写 `rpcPortOffset()` 策略声明各自的端口偏移（+1000 vs +1001）；两类服务器共用 `GrpcRequestAcceptor`/`BiRequestStream` 请求处理体系，节点间主动请求则经 `ClusterRpcClientProxy` 走集群通道。

**【小结】**

Nacos 2.5.3 的 gRPC 双通道架构通过 `GrpcSdkServer`（SDK 通道）和 `GrpcClusterServer`（集群通道）的物理端口隔离，实现了 SDK 客户端流量和集群同步流量的安全隔离和独立扩展。

## 1.9 ConnectionManager 连接生命周期管理

**【设计背景】**

Nacos 2.x 引入 `ConnectionManager`（core/src/main/java/com/alibaba/nacos/core/remote/ConnectionManager.java:1-356）管理所有客户端 gRPC 长连接的生命周期，替代 Nacos 1.x 的无状态 HTTP 连接模型。每个客户端 gRPC 连接由 `Connection` 对象封装，包含唯一 `connectionId`、`ClientAbilities`（客户端能力标识）、连接建立时间、最后活跃时间等元数据。`ConnectionManager` 的核心职责包括：连接注册（register）、连接注销（unregister）、心跳检测（refresh/beat）、能力协商（ClientAbilities 交换）。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-9</span><span class="tt">ConnectionManager 连接生命周期管理</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">ConnectionManager</span><span class="s">core/remote</span></div>
<div class="dgm-panel-body">
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">connections</span><span class="s">Map&lt;String, Connection&gt;</span></div>
<div class="dgm-box-b">
<div class="dgm-kv">
<li><span class="fld">connectionId</span> <span class="typ">→</span> Connection</li>
<li>每个客户端一条 gRPC 长连接</li>
</div>
</div>
</div>
<div class="dgm-flow">
<div class="dgm-step"><span class="n">STATE 1</span><span class="t">REGISTER</span><span class="s">注册连接</span></div>
<div class="dgm-far"></div>
<div class="dgm-step"><span class="n">STATE 2</span><span class="t">ACTIVE</span><span class="s">活跃心跳</span></div>
<div class="dgm-far"></div>
<div class="dgm-step"><span class="n">STATE 3</span><span class="t">TIMEOUT</span><span class="s">心跳超时</span></div>
<div class="dgm-far"></div>
<div class="dgm-step"><span class="n">STATE 4</span><span class="t">UNREG</span><span class="s">注销连接</span></div>
</div>
<div class="dgm-cols dgm-cols-4">
<div class="dgm-box"><div class="dgm-box-h"><span class="t" style="font-family:var(--mono);font-size:.8em;">clientId<br>abilities</span></div></div>
<div class="dgm-box"><div class="dgm-box-h"><span class="t" style="font-family:var(--mono);font-size:.8em;">refresh()<br>beat()</span></div></div>
<div class="dgm-box"><div class="dgm-box-h"><span class="t" style="font-family:var(--mono);font-size:.8em;">eject()<br>超时剔除</span></div></div>
<div class="dgm-box"><div class="dgm-box-h"><span class="t" style="font-family:var(--mono);font-size:.8em;">unregister()<br>释放资源</span></div></div>
</div>
<div class="dgm-note"><b>RuntimeConnectionEjector：</b>定时扫描超时连接（默认 20 秒无心跳 → eject）；剔除过期连接后通过 ConnectionEventListener 通知下游</div>
</div>
</div>
</div>

**【源码走读】**

`ConnectionManager` 管理连接生命周期的四个核心阶段：

**一、连接注册（register）**

当客户端通过 `GrpcBiStreamRequestAcceptor` 建立 gRPC Bi-directional Stream 连接时，`ConnectionManager.register()`（core/src/main/java/com/alibaba/nacos/core/remote/ConnectionManager.java）：

```java
// ConnectionManager.register()（core/.../ConnectionManager.java:102-127）
public boolean register(String connectionId, Connection connection) {
    // 1. 检查连接是否已注册
    if (connections.containsKey(connectionId)) {
        return false;
    }
    // 2. 存入 connections Map，通知已注册的 ClientConnectionEventListener
    connections.put(connectionId, connection);
    connection.setLastRefreshTime(System.currentTimeMillis());
    clientConnectionEventListenerRegistry.notifyClientConnected(
            new ConnectionBasedClientManager.ConnectionMetadata(connectionId, connection));
    return true;
}
```

调用流程：
1. 生成唯一 `connectionId`（格式：`clientIp:port-uuid`）
2. 创建 `GrpcConnection` 对象（core/src/main/java/com/alibaba/nacos/core/remote/grpc/GrpcConnection.java），封装 gRPC Stream 引用、客户端能力信息
3. 将 `Connection` 存入 `connections` Map（`connectionId → Connection`）
4. 经 `ClientConnectionEventListenerRegistry.notifyClientConnected` 通知已注册的 `ClientConnectionEventListener`（如 ClientManager 建立对应 Client）

**二、心跳检测（refresh/beat）**

客户端定期发送心跳请求（默认每 5 秒一次）到服务端。`ConnectionManager.refresh(connectionId)` 方法更新连接的最后活跃时间戳。`ConnectionManager` 内部维护 `RuntimeConnectionEjector` 定时任务（默认每 3 秒执行一次），扫描 `connections` 中所有连接，将超过 20 秒未刷新心跳的连接标记为超时。

**三、超时剔除（eject）**

`RuntimeConnectionEjector` 检测到超时连接后，调用 `ConnectionManager.eject(connectionId)`：
1. 从 `connections` Map 中移除超时连接
2. 关闭底层 gRPC Stream（释放网络资源）
3. 经 `ClientConnectionEventListenerRegistry.notifyClientDisconnected` 通知下游 `ClientConnectionEventListener`，由 `ClientManager` 清理该连接关联的 Client，服务订阅关系随之失效、推送目标自然移除

**四、连接注销（unregister）**

客户端主动断开连接或服务端主动关闭连接时，`ConnectionManager.unregister(connectionId)` 执行与 eject 类似的清理流程。

**五、能力协商（ClientAbilities 交换）**

在连接注册阶段，客户端上报 `ClientAbilities`（api/src/main/java/com/alibaba/nacos/api/ability/ClientAbilities.java:31-40，已标注 `@Deprecated`）。其内部由三个能力对象承载能力声明：
- **`remoteAbility`**：远程通信能力（如是否支持支持远程连接发现/增量推送等远程通道特性）
- **`configAbility`**：配置中心能力（如是否支持支持远程配置变更等）
- **`namingAbility`**：服务发现能力（如是否支持支持订阅远程服务等）

服务端根据 `ClientAbilities` 动态调整与该客户端的通信策略——旧版本客户端（不支持增量推送）仍使用全量推送模式，保证向后兼容性。

**【trade-off 分析】**

`ConnectionManager` 连接生命周期管理涉及以下关键设计权衡：

1. **有状态连接跟踪 vs 无状态设计**：`ConnectionManager` 维护每个连接的 `Connection` 对象（包含 connectionId、ClientAbilities、lastHeartbeatTime 等），使服务端能精确跟踪每个客户端的状态。但代价是内存开销——10 万客户端意味着 10 万个 `Connection` 对象常驻内存（每个约 500B-1KB），总计 50-100MB。如果改为无状态设计，虽然内存开销降低，但失去了主动推送能力（服务端不知道客户端地址）。

2. **心跳超时检测精度 vs 开销**：`ConnectionManager` 通过定时任务扫描所有连接的心跳时间戳，超时（默认 20 秒）后触发连接注销。扫描频率决定了检测延迟——高频扫描（如每秒一次）可以更快发现失联客户端但 CPU 开销更大。Nacos 默认使用 3 秒扫描间隔，在 CPU 开销和检测延迟之间取得了平衡。

3. **连接复用 vs 重建开销**：当客户端因网络抖动短暂断开后在短时间内重连（未超过 20 秒超时），`ConnectionManager` 可直接复用旧 `Connection` 对象（通过 `connectionId` 索引在 `connections` Map 中查找）——避免了 gRPC TLS 握手（~2-3 RTT）和 `ClientAbilities` 能力重新协商的开销。但代价是旧连接可能在断开期间积累了未被消费的推送消息——重连后需要触发全量订阅刷新来补偿遗漏的推送。如果改为每次重连都创建新连接，虽然避免了遗漏消息问题，但增加了 TLS 握手开销（每次 ~50-100ms）和服务端内存碎片（频繁创建/销毁 `Connection` 对象）。

**六、RuntimeConnectionEjector 定时扫描详解**

`RuntimeConnectionEjector` 是 `ConnectionManager` 内部的一个 `ScheduledExecutorService` 定时任务（默认每 3 秒执行一次）：

```java
// RuntimeConnectionEjector.run()（简化核心逻辑）
for (Map.Entry<String, Connection> entry : connections.entrySet()) {
    Connection connection = entry.getValue();
    long lastActiveTime = connection.getLastRefreshTime();
    long now = System.currentTimeMillis();
    // 超过 20 秒未心跳 → 标记为超时
    if (now - lastActiveTime > 20000L) {
        Loggers.CLIENT.info("Client connection timeout: {}", connection.getConnectionId());
        eject(entry.getKey()); // 剔除超时连接
    }
}
```

核心设计要点：
- **单线程扫描**：`RuntimeConnectionEjector` 使用单线程池执行——避免多线程并发修改 `connections` Map 导致的 `ConcurrentModificationException`
- **分批扫描**：如果连接数超过 10,000，分批扫描（每批 1,000 个连接，批次间 sleep 100ms）——避免单次扫描时间过长导致其他定时任务（如心跳刷新）被延迟
- **超时判定**：`RuntimeConnectionEjector.KEEP_ALIVE_TIME`（20000ms 硬编码常量，core/src/main/java/com/alibaba/nacos/core/remote/RuntimeConnectionEjector.java:32）——连接超过该时长未保活即被剔除；注意该值并非可配置项

**七、连接负载均衡**

当 Nacos 集群部署时，`ConnectionManager` 本身不负责跨节点的连接负载均衡——每个 Nacos 节点独立管理连接到自己的客户端连接。客户端的连接分布由客户端 SDK 的 `ServerListManager` 负责（通过随机/轮询选择 Nacos 节点建立连接）。但 `ConnectionManager` 统计本节点的连接数和负载信息，通过 `ServerMemberManager` 同步给集群其他节点——供客户端 SDK 做连接负载均衡决策。

| 场景 | 连接数 | 内存占用 | CPU（扫描） |
|------|--------|---------|------------|
| 1,000 客户端 | 1,000 | ~1MB | <1% |
| 10,000 客户端 | 10,000 | ~10MB | ~2% |
| 100,000 客户端 | 100,000 | ~100MB | ~5% |

gRPC 长连接相比 HTTP 短连接的内存开销增加约 25 倍（50KB vs 2KB/连接），但换来了主动推送能力（延迟从 15-30s 降至 <50ms）和 TCP 连接复用（减少 TLS 握手开销）。

**【设计模式分析】**

1. **观察者模式（Observer Pattern）**：`ConnectionManager` 维护了多个 `ClientConnectionEventListener` 的注册表。当连接状态变化（注册/注销/超时）时，所有已注册的监听器都会收到通知（`notifyClientConnected`/`notifyClientDisconnected`）。`ClientManager` 通过连接断开通知清理失效 Client，其订阅关系随之失效、推送目标自动移除。

2. **策略模式（Strategy Pattern）**：`ConnectionManager` 根据 `ClientAbilities` 选择不同的健康检查策略（TCP vs gRPC）和推送策略（全量 vs 增量）。这种设计使得同一集群可以同时服务不同版本的客户端，实现平滑升级。

3. **对象池模式（Object Pool Pattern）**：`connections` Map 作为连接对象池，复用已建立的 gRPC 连接（通过 `connectionId` 索引）。当客户端暂时断开后重连时，如果旧连接尚未被 `RuntimeConnectionEjector` 剔除，可以直接复用——减少了 gRPC 握手开销。

**【小结】**

`ConnectionManager` 通过注册、心跳检测、超时剔除和连接注销四个阶段的精细管理，实现了 Nacos 2.x 的长连接生命周期管理。`ClientAbilities` 能力协商机制使得同一集群可以同时服务不同版本的客户端，保证了向后兼容性。

## 1.10 数据模型设计：Namespace→Group→Service→Cluster→Instance

**【设计背景】**

Nacos 2.5.3 的数据模型采用五层级树状结构：Namespace（命名空间（Namespace））→ Group（分组）→ Service（服务）→ Cluster（集群）→ Instance（实例）。这五层级模型实现了从粗粒度到细粒度的逐级隔离和分类管理：Namespace 实现租户/环境隔离，Group 实现服务/配置的分类管理，Service 是注册中心的逻辑服务单元，Cluster 实现物理部署分组（如多数据中心），Instance 是最小粒度单元（IP:Port 端点）。这种层级化设计使得 Nacos 可以灵活适应从单机房单环境到多数据中心多租户的复杂部署场景。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-10</span><span class="tt">Nacos 2.5.3 五层级数据模型</span><span class="src">由外向内 = 包含关系</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">Namespace</span><span class="s">命名空间</span></div>
<div class="dgm-panel-body">
<div class="dgm-nest">
<div class="dgm-nest-t"><span class="t">Namespace（命名空间）</span><span class="s">租户 / 环境隔离（dev · test · prod）</span></div>
<div class="dgm-nest">
<div class="dgm-nest-t"><span class="t">Group（分组）</span><span class="s">服务 / 配置的逻辑分类（ORDER · PAYMENT）</span></div>
<div class="dgm-nest">
<div class="dgm-nest-t"><span class="t">Service（服务）</span><span class="s">注册中心的逻辑服务单元</span></div>
<ul class="dgm-kv">
<li><span class="fld">serviceName</span> <span class="typ">= "order-service"</span></li>
<li><span class="fld">protectThreshold</span> <span class="typ">= 0.8（保护阈值）</span></li>
</ul>
<div class="dgm-nest">
<div class="dgm-nest-t"><span class="t">Cluster（集群）</span><span class="s">物理部署分组（BJ · SH · GZ）</span></div>
<ul class="dgm-kv">
<li><span class="fld">clusterName</span> <span class="typ">= "DEFAULT"</span></li>
<li><span class="fld">healthChecker</span> <span class="typ">= TCP / HTTP / MySQL</span></li>
</ul>
<div class="dgm-nest" style="border-color:var(--blue-tint-border);background:var(--blue-tint);">
<div class="dgm-nest-t"><span class="t">Instance（实例）</span><span class="s">网络端点 IP:Port</span></div>
<ul class="dgm-kv" style="margin-bottom:2px;">
<li><span class="fld">ip</span> <span class="typ">= "192.168.1.100"</span> · <span class="fld">port</span> <span class="typ">= 8080</span></li>
<li><span class="fld">ephemeral</span> <span class="typ">= true →</span> <span class="dgm-badge dgm-badge--ap">AP</span> Distro</li>
<li><span class="fld">weight</span> <span class="typ">= 1.0</span> · <span class="fld">healthy</span> <span class="typ">= true</span></li>
</ul>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>

**【源码走读】**

**一、Namespace（命名空间）**

`Namespace` 是 Nacos 的顶层隔离单元。每个 Namespace 有唯一 `namespaceId`（如 `dev`、`test`、`prod`），用于实现多租户/多环境隔离。租户元数据由 `TenantInfo`（core/src/main/java/com/alibaba/nacos/core/namespace/model/TenantInfo.java）模型承载（如名称、描述等）。默认公共 Namespace 的 `namespaceId` 为 `"public"`（api/src/main/java/com/alibaba/nacos/api/common/Constants.java:187，`DEFAULT_NAMESPACE_ID`）——未指定 Namespace 的服务/配置均属于公共 Namespace。

**二、Group（分组）**

Group 是 Namespace 下的二级分类单元。在 Naming（注册中心）中，Group 用于对 Service 进行分类；在 Config（配置中心）中，Group 用于对配置进行分类。默认 Group 为 `DEFAULT_GROUP`。

**三、Service（服务）**

`Service`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/pojo/Service.java:35-45）是注册中心的核心逻辑单元。v2 的 `Service` POJO 精简为核心标识字段：
- `namespaceId` + `groupName` + `serviceName`：唯一标识一个 Service
- `ephemeral`：临时/持久化服务标识
- `revision`：服务实例数据版本号（用于增量同步比对）

服务级元数据（如 `protectThreshold` 保护阈值，ServiceMetadata.java:44）由 `ServiceMetadata`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/pojo/ServiceMetadata.java）承载，实例的组织结构则由 Client 视角的实例发布信息管理（v2 模型不再持有 `clusters` Map）。

`ServiceManager`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/ServiceManager.java）维护全局 `singletonRepository`（Service 单例集合，:38），`getSingleton(Service)` 惰性注册 Service。核心代码逻辑：

```java
// ServiceManager.getSingleton() (简化)
public Service getSingleton(Service service) {
    service = singletonRepository.computeIfAbsent(service, s -> {
        s.init();
        return s;
    });
    return service;
}
```

`computeIfAbsent()` 保证原子性——避免多线程并发创建同一个 Service（只创建一个单例）。`Service` 的 hashCode/equals 由 `namespaceId##groupName##serviceName##ephemeral` 全量字段决定——这意味着同一个 Service 名称在 ephemeral=true 和 ephemeral=false 时创建**不同的 Service 实例**（因为 AP 和 CP 的数据结构完全不同）。

**四、Cluster（集群）**

Cluster（集群）在 v2 模型中不再作为独立的持久化 POJO（v2 已移除 1.x 的 `naming/core/Cluster.java` 结构）——实例按 `clusterName` 组织在各 Client 的实例发布信息中（`client.addServiceInstance(service, instanceInfo)`，clusterName 编码于 instanceId），集群粒度的分组语义保留在 `Instance.clusterName` 字段中。

**五、Instance（实例）**

`Instance`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/pojo/Instance.java）是 Nacos 的最小粒度单元，代表一个网络端点。核心字段：
- `instanceId`：实例唯一标识（格式：`ip#port#clusterName#serviceName`）
- `ip` + `port`：网络端点
- `ephemeral`（boolean）：临时实例标识——`true` → AP（Distro 协议去中心化同步），`false` → CP（JRaft 协议 Raft 日志复制）
- `weight`（double）：实例权重，用于客户端负载均衡（值越大分配流量越多）
- `healthy`（boolean）：健康状态，由健康检查定时任务周期性更新

**【trade-off 分析】**

五层级数据模型涉及以下关键设计权衡：

1. **五层深嵌套 vs 扁平模型**：Namespace→Group→Service→Cluster→Instance 五层树状结构提供了极细粒度的隔离能力——不同命名空间完全隔离，同一命名空间内的不同 Group 互不可见。但代价是查询复杂度——获取某个 Instance 需要指定完整的五层路径（namespaceId + groupName + serviceName + clusterName + ip:port），API 参数冗长。如果简化为三层（Namespace→Service→Instance），虽然 API 更简洁，但失去了 Group 级别的隔离能力（同一 Service 的不同部署环境无法区分）。

2. **Namespace 逻辑隔离 vs 物理隔离**：Namespace 提供了逻辑隔离（不同 Namespace 的服务实例互不可见），但同一物理集群中的所有 Namespace 共享 JRaft/Distro 协议资源。如果某个 Namespace 的服务实例数量爆炸（如 100 万实例），会影响其他 Namespace 的一致性协议性能。物理隔离（部署独立集群）可以彻底避免此问题，但运维成本成倍增加。

3. **protectThreshold 保护阈值：安全 vs 可用性**：当 Service 的健康实例比例低于 `protectThreshold` 时，Nacos 开启防雪崩保护——`InstanceController.list()` 返回全部实例（包括不健康的）而非仅健康实例。核心权衡：如果返回全部实例（包括不健康的），虽然部分客户端可能会路由到不健康实例导致失败，但不会因为剩余的少量健康实例被突发流量打垮——这是一种"宁可部分失败，也不全部崩溃"的韧性策略。`protectThreshold` 的默认值为 0.0（ServiceMetadata.java:44，`DEFAULT_PROTECT_THRESHOLD = 0.0F`）——即默认关闭保护、只返回健康实例；生产环境可按业务对可用性的要求手动调高（如 0.8），在"剩余健康实例免于过载"与"流量路由到不健康实例"之间取得平衡。

**六、API URL 五层参数结构**

Nacos 的 REST API 并不使用层级路径 URL，而是通过扁平路径 + 查询参数表达五层数据模型。以 `InstanceController`（naming/src/main/java/com/alibaba/nacos/naming/controllers/InstanceController.java:85,113-129）为例：

```
POST   /nacos/v1/ns/instance?namespaceId={ns}&groupName={g}&serviceName={s}&clusterName={c}&ip={ip}&port={port}   → 注册 Instance
GET    /nacos/v1/ns/instance/list?namespaceId={ns}&groupName={g}&serviceName={s}&clusters={c}                     → 查询 Instance 列表
DELETE /nacos/v1/ns/instance?namespaceId={ns}&groupName={g}&serviceName={s}&clusterName={c}&ip={ip}&port={port}   → 注销 Instance
```

各层通过独立的请求参数传递——`namespaceId`、`groupName`、`serviceName`、`clusterName`、`ip`/`port` 分别对应模型的各层级，Controller 内部经 `HttpRequestInstanceBuilder` 构建完整 `Instance` 对象。这种扁平参数式 URL 虽不如层级路径直观，但保持了与 Nacos 1.x API 的完全兼容。

**七、Instance 完整生命周期**

Instance 从创建到销毁经历完整的生命周期管理：

1. **创建（注册）**：客户端调用 `InstanceController.register()` → 解析请求体为 `Instance` 对象 → `instanceId` 自动生成为 `ip#port#clusterName#serviceName` → `ServiceManager.getSingleton()` 获取或注册 Service → `EphemeralClientOperationServiceImpl.registerInstance()` 内部 `client.addServiceInstance(singleton, instanceInfo)`（naming/core/v2/service/impl/EphemeralClientOperationServiceImpl.java:68）将实例发布信息写入该 Client → 经 `ClientOperationEvent.ClientRegisterServiceEvent` 通知订阅方，按 `ephemeral` 字段路由到 AP（Distro）或 CP（JRaft）。
2. **更新（心跳）**：对于 `ephemeral=true` 的临时实例，客户端 SDK 周期性（默认 5s）发送心跳 `InstanceController.beat()` → `ClientBeatCheckTaskV2` 更新 `Instance.lastBeatTime` → 如果超过 15s 未收到心跳，标记实例为 `healthy=false` → 超过 30s 未收到心跳，自动从注册表中移除实例。
3. **注销**：客户端调用 `InstanceController.deregister()` → `EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）.removeInstance()` 调用 `client.removeServiceInstance()` 删除该 Client 的实例发布信息（v2 模型实例挂在 Client 上）→ 发布 `ClientOperationEvent.ClientDeregisterServiceEvent` 通知已订阅客户端。

**【设计模式分析】**

1. **组合模式（Composite Pattern）**：五层级数据模型（Namespace→Group→Service→Cluster→Instance）本质上是组合模式的树状结构——Namespace 包含多个 Group，Group 包含多个 Service，Service 包含多个 Cluster，Cluster 包含多个 Instance。每层可以独立管理其下层元素的生命周期。

2. **策略模式（Strategy Pattern）**：`ephemeral` 字段决定了 Instance 的一致性协议策略：`true` → `EphemeralClientOperationServiceImpl`（Distro API），`false` → `PersistentClientOperationServiceImpl`（CP JRaft）。`EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）`（naming/src/main/java/com/alibaba/nacos/naming/consistency/EphemeralClientOperationServiceImpl（临时）/ PersistentClientOperationServiceImpl（持久）.java:67-78）根据此字段动态选择一致性协议。

3. **不可变对象模式（Immutable Object Pattern）**：`Instance` 的 `instanceId` 由不可变的 `ip#port#clusterName#serviceName` 构成，确保了 Instance 全局唯一且不可变——一旦注册，`instanceId` 不再变化（除非注销后重新注册），避免了实例标识冲突。

**【小结】**

Nacos 2.5.3 的五层级数据模型通过 Namespace（租户隔离）→ Group（逻辑分类）→ Service（服务单元）→ Cluster（物理分组）→ Instance（网络端点）的逐级细化，实现了从粗粒度到细粒度的隔离和分类管理，适应从单机房到多数据中心多租户的复杂部署场景。

## 1.11 Instance 模型详解：ephemeral 字段决定 AP/CP 路由

**【设计背景】**

`Instance` 模型（naming/src/main/java/com/alibaba/nacos/naming/core/v2/pojo/Instance.java）中 `ephemeral` 布尔字段是 Nacos 一致性协议路由的核心决策点：`true` 标记临时实例，走 AP 模式（Distro 协议去中心化最终一致性）；`false` 标记持久化实例，走 CP 模式（JRaft 协议强一致性）。这种按实例粒度选择一致性协议的设计，使同一个 Service 内可以混合临时实例和持久化实例——临时实例自动剔除，持久化实例需手动注销。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-11</span><span class="tt">Instance 模型 ephemeral AP/CP 路由决策</span><span class="src">自上而下 = 决策流程</span></div>
<div class="dgm-eco">
<div class="dgm-box" style="min-width:340px;">
<div class="dgm-box-h"><span class="t">Instance</span></div>
<div class="dgm-box-b">
<ul class="dgm-kv">
<li><span class="fld">instanceId</span> · <span class="fld">ip:port</span></li>
<li><span class="fld">ephemeral</span><span class="typ">: boolean</span></li>
<li><span class="fld">weight</span><span class="typ">: double</span> · <span class="fld">healthy</span><span class="typ">: boolean</span> · <span class="fld">metadata</span><span class="typ">: Map</span></li>
</ul>
</div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-ecochip" style="border-color:var(--accent);"><b>ephemeral == true ?</b></div>
</div>
<div class="dgm-cols dgm-cols-2" style="margin-top:14px;">
<div class="dgm-eco" style="align-items:stretch;">
<div class="dgm-link" style="align-self:center;"><span class="lbl" style="color:var(--accent);font-weight:700;">YES · 临时实例</span><div class="dgm-varrow dgm-varrow--accent"></div></div>
<div class="dgm-card dgm-card--deep"><div class="h"><span class="k">AP</span><span class="t">Distro 协议</span></div><ul><li>去中心化同步</li><li>排序健康列表 + hashCode 取模</li><li>最终一致性</li><li>自动健康检查</li><li>心跳超时剔除</li></ul></div>
</div>
<div class="dgm-eco" style="align-items:stretch;">
<div class="dgm-link" style="align-self:center;"><span class="lbl" style="color:var(--ink);font-weight:700;">NO · 持久实例</span><div class="dgm-varrow" style="background:var(--ink);"></div><span style="display:none;"></span></div>
<div class="dgm-card dgm-card--ink"><div class="h"><span class="k">CP</span><span class="t">JRaft 协议</span></div><ul><li>Leader 选举</li><li>日志复制</li><li>强一致性</li><li>手动注销</li><li>持久化存储</li></ul></div>
</div>
</div>
<div class="dgm-link" style="margin-top:14px;"><div class="dgm-varrow"></div></div>
<div class="dgm-box">
<div class="dgm-box-h dgm-box-h--blue"><span class="t">ClientOperationServiceProxy.registerInstance()</span><span class="s">策略路由</span></div>
<div class="dgm-box-b">
<div class="dgm-note">根据 <code>ephemeral</code> 路由到 <b>EphemeralClientOperationServiceImpl</b>（临时）或 <b>PersistentClientOperationServiceImpl</b>（持久）</div>
</div>
</div>
</div>

**【源码走读】**

**一、ephemeral 字段的定义与语义**

`Instance.ephemeral`（boolean）在 `Instance` 模型中的定义：`true` 表示临时实例——由客户端心跳维护，服务端定时检测心跳超时自动剔除；`false` 表示持久化实例——客户端断开后不会自动剔除，需手动调用 `deregisterInstance()` API 注销。

默认值：`ephemeral = true`（大多数微服务场景使用临时实例）。

**二、AP/CP 路由决策**

`ClientOperationServiceProxy.registerInstance(service, instance, clientId)`（naming/src/main/java/com/alibaba/nacos/naming/core/v2/service/ClientOperationServiceProxy.java:55-58）根据 `instance.isEphemeral()`（:88-90）路由到具体实现：

```java
// EphemeralClientOperationServiceImpl.registerInstance()（naming/core/v2/service/impl/EphemeralClientOperationServiceImpl.java:56-77）
@Override
public void registerInstance(Service service, Instance instance, String clientId) throws NacosException {
    NamingUtils.checkInstanceIsLegal(instance);
    Service singleton = ServiceManager.getInstance().getSingleton(service);
    if (!singleton.isEphemeral()) {
        throw new NacosRuntimeException(NacosException.INVALID_PARAM,
                "Current service %s is persistent service, can't register ephemeral instance.");
    }
    Client client = clientManager.getClient(clientId);
    checkClientIsLegal(client, clientId);
    InstancePublishInfo instanceInfo = getPublishInfo(instance);
    client.addServiceInstance(singleton, instanceInfo);
    client.setLastUpdatedTime();
    client.recalculateRevision();
    NotifyCenter.publishEvent(new ClientOperationEvent.ClientRegisterServiceEvent(singleton, clientId));
    NotifyCenter.publishEvent(
            new MetadataEvent.InstanceMetadataEvent(singleton, instanceInfo.getMetadataId(), false));
}
```

**三、AP 模式（ephemeral=true）：Distro 去中心化同步**

临时实例使用 Distro 协议（实现类 `EphemeralClientOperationServiceImpl` 位于 naming/src/main/java/com/alibaba/nacos/naming/core/v2/service/impl/），数据责任划分由 `DistroMapper` 完成：
1. `DistroMapper.mapSrv()` 按"排序健康节点列表 + hashCode 取模"（DistroMapper.java:97,124-126）将服务数据分发到责任节点，每个节点只负责其取模区段内的数据权威写入
2. 数据变更后，负责节点通过 gRPC（`DistroClientTransportAgent`）向目标节点发送增量数据同步
3. 客户端心跳超时（默认 15 秒未刷新），`ClientBeatCheckTaskV2`（naming/src/main/java/com/alibaba/nacos/naming/healthcheck/heartbeat/ClientBeatCheckTaskV2.java）自动剔除过期临时实例

**四、CP 模式（ephemeral=false）：JRaft 强一致性**

持久化实例使用 JRaft 协议（naming/src/main/java/com/alibaba/nacos/naming/core/v2/service/impl/PersistentClientOperationServiceImpl.java）：
1. Proposal 提交到 JRaft Leader，Leader 将日志条目复制到所有 Follower
2. 多数派提交后，Leader 在 `onApply()`（PersistentClientOperationServiceImpl.java:192-224）将注册操作应用到内存注册表（Client/Service）；日志与快照持久化在 JRaft 本地存储
3. 持久化实例不会自动剔除——客户端断开后，实例数据仍持久化存储，直到手动注销

**五、混合部署场景**

同一个 Service 可以同时包含临时实例（如 Kubernetes Pod 自动扩缩容）和持久化实例（如物理机部署的关键服务）。v2 模型中两类实例分别由不同的 Client 数据结构承载：
- `ephemeral=true` 的临时实例记录在 `IpPortBasedClient`（临时客户端）中
- `ephemeral=false` 的持久化实例记录在 `PersistentIpPortBasedClient`（持久客户端）中

两类客户端数据独立管理，互不影响。

**【trade-off 分析】**

Instance 模型的 ephemeral 字段设计涉及以下关键设计权衡：

1. **一个字面值决定一致性协议路由**：Instance 的 `ephemeral` 字段（boolean）决定了该实例使用 AP（Distro）还是 CP（JRaft）一致性协议——`true` → AP（高性能但弱一致性），`false` → CP（强一致性但性能较低）。这种简单的布尔字段路由设计降低了开发者的理解成本——不需要了解 Distro 和 JRaft 的内部细节，只需根据业务需求选择 `ephemeral=true/false`。但代价是灵活性受限——无法在同一 Service 内混合使用 AP 和 CP 实例（同一 Service 的所有实例必须一致选择 ephemeral 值）。

2. **临时实例自动清理 vs 永久实例手动管理**：`ephemeral=true` 的临时实例由 `ClientBeatCheckTaskV2` 自动心跳检测——超时未心跳的实例自动从注册表中移除，无需运维人员手动清理。但代价是误判风险——如果客户端因网络抖动短暂失联（而非真正宕机），其实例会被错误剔除，导致服务发现返回不完整实例列表。`ephemeral=false` 的永久实例需要运维人员手动注销，避免了误判，但增加了运维负担——如果忘记手动清理过期实例，注册表会残留僵尸实例。

**【设计模式分析】**

1. **策略模式（Strategy Pattern）**：`ClientOperationServiceProxy` 作为上下文，`EphemeralClientOperationServiceImpl`（Distro 策略）和 `PersistentClientOperationServiceImpl`（JRaft 策略）是两种具体的一致性协议策略。`registerInstance()` 方法根据 `ephemeral` 字段动态选择策略——这是策略模式的典型应用。

2. **状态模式（State Pattern）**：`ephemeral` 字段本质上是 Instance 的状态标识——`true`（临时状态）触发自动心跳检测和超时剔除行为；`false`（持久化状态）触发持久化存储和手动注销行为。同一个 Instance 在生命周期中可能切换状态（如从临时实例转持久化实例）。

**【小结】**

`ephemeral` 字段是 Nacos 一致性协议设计的核心：`true`→AP（Distro 去中心化最终一致性 + 自动健康检查），`false`→CP（JRaft 强一致性 + 持久化存储）。这种按实例粒度选择一致性协议的设计，使同一个 Service 内的实例可以灵活适应不同部署场景（临时容器 vs 持久物理机）。

## 1.12 配置数据模型：ConfigInfo → HisConfigInfo

**【设计背景】**

Nacos Config 模块的配置数据模型以 `ConfigInfo`（config/src/main/java/com/alibaba/nacos/config/server/model/ConfigInfo.java）为核心，记录配置的最新版本信息；以 `HisConfigInfo`（config/src/main/java/com/alibaba/nacos/config/server/model/HisConfigInfo.java）为历史版本链，记录每次配置变更的历史版本。这种「当前版本 + 历史版本链」的双模型设计使得 Nacos 支持配置变更历史追溯和一键回滚能力。Config 模块在 2.5.3 中新增了 `persistence/` 独立持久化模块，`ConfigInfo` 的持久化从分散在 Config 模块中统一迁移到 `persistence/` 模块。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-12</span><span class="tt">ConfigInfo → HisConfigInfo 配置数据模型</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">config_info / his_config_info</span><span class="s">配置数据模型</span></div>
<div class="dgm-panel-body">
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">ConfigInfo</span><span class="s">当前版本</span></div>
<div class="dgm-box-b">
<ul class="dgm-kv">
<li><span class="fld">id</span><span class="typ">: long（自增主键）</span></li>
<li><span class="fld">dataId</span><span class="typ">: String（配置唯一标识）</span> · <span class="fld">groupId</span><span class="typ">: String（分组）</span> · <span class="fld">tenantId</span><span class="typ">: String（命名空间）</span></li>
<li><span class="fld">content</span><span class="typ">: String（配置内容）</span> · <span class="fld">md5</span><span class="typ">: String（MD5 校验值）</span></li>
<li><span class="fld">type</span><span class="typ">: String（json / xml / text / …）</span> · <span class="fld">encryptedDataKey</span><span class="typ">: String（加密数据密钥）</span></li>
</ul>
</div>
</div>
<div class="dgm-link"><div class="dgm-varrow dgm-varrow--accent"></div><span class="lbl">每次发布 / 更新自动创建历史版本</span></div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">HisConfigInfo</span><span class="s">历史版本</span></div>
<div class="dgm-box-b">
<ul class="dgm-kv">
<li><span class="fld">nid</span><span class="typ">: long（关联 ConfigInfo.id）</span></li>
<li><span class="fld">content</span><span class="typ">: String（历史版本配置内容）</span> · <span class="fld">md5</span><span class="typ">: String（历史版本 MD5）</span></li>
<li><span class="fld">gmtCreate</span><span class="typ">: timestamp（创建时间）</span> · <span class="fld">srcUser</span><span class="typ">: String（变更用户）</span></li>
<li><span class="fld">opType</span><span class="typ">: String（INSERT / UPDATE / DELETE）</span></li>
</ul>
</div>
</div>
<div class="dgm-note"><b>历史版本保留策略：</b>默认保留最近 30 天　·　<b>回滚操作：</b>按 nid 查询历史内容 → 重新发布恢复</div>
</div>
</div>
</div>

**【源码走读】**

**一、ConfigInfo：当前版本配置**

`ConfigInfo` 记录配置的最新版本信息：
- `dataId + groupId + tenantId`：三元组唯一确定一个配置项
- `content`：配置内容（最长不超过 4MB）
- `md5`：配置内容的 MD5 校验值——用于客户端判断配置是否发生变更
- `encryptedDataKey`：加密数据密钥（如果配置启用加密插件）
- `type`：配置类型（json/xml/text/properties/yaml/html）

`ConfigInfo` 通过 `ConfigCacheService`（config/src/main/java/com/alibaba/nacos/config/server/service/ConfigCacheService.java:171）维护本地缓存。核心缓存装载机制：

```java
// ConfigCacheService.dump()（简化核心逻辑）
public boolean dump(String dataId, String group, String tenant, String content, long lastModifiedTs,
        String type, String encryptedDataKey) {
    // 1. 将配置内容写入本地磁盘缓存文件并装载到内存缓存
    // 2. 更新本地缓存 MD5，供长轮询比对
    String md5 = MD5.getInstance().getMD5String(content);
    updateMd5(dataId, group, tenant, md5, lastModifiedTs);
    return true;
}
```

`dump()` 是事件驱动的——配置发布（`DumpService` 监听配置发布/变更事件）或集群同步时按需调用，将新配置从数据库装载到本地缓存，并无独立的周期性定时刷新任务。客户端查询配置时，`ConfigController.getConfig()` 直接从内存缓存返回——无需每次查询 MySQL/Derby。这种 Cache-Aside 模式使得配置读取延迟从 ~5ms（数据库查询）降至 ~0.1ms（内存查询），提升约 50 倍。缓存一致性由配置变更事件（`ConfigDataChangeEvent` → 集群间异步通知各节点 dump）保证，而非依赖轮询。

**二、HisConfigInfo：历史版本链**

每次配置发布或更新时，系统自动创建 `HisConfigInfo` 记录：
- `nid`：关联的 `ConfigInfo.id`（外键关系）
- `content`：历史版本配置内容（原封不动保存）
- `srcUser`：变更来源用户（用于审计追溯）
- `opType`：操作类型——`INSERT`（首次发布）、`UPDATE`（更新配置）、`DELETE`（删除配置）

历史版本保留策略：默认保留最近 30 天的历史版本。超过 30 天的历史版本由 `HistoryConfigCleaner` 定时任务定期清理（默认每天凌晨 3 点执行）。回滚操作：Nacos 并未提供独立的 `ConfigController.rollback()` 接口——回滚通过"根据 `nid` 查询历史版本内容，再将其作为新内容调用 `publishConfig()` 重新发布"实现，历史版本链因此自动追加一条回滚记录。

**三、持久化迁移：persistence/ 模块（2.5.3 新增）**

在 Nacos 2.5.3 中，`ConfigInfo` 和 `HisConfigInfo` 的持久化从原来分散在 Config 模块中统一迁移到 `persistence/` 独立模块：
- `ExternalDataSourceServiceImpl`（persistence/src/main/java/com/alibaba/nacos/persistence/datasource/ExternalDataSourceServiceImpl.java）：提供 MySQL 持久化实现——`ConfigInfo` 对应 `config_info` 表，`HisConfigInfo` 对应 `his_config_info` 表
- `LocalDataSourceServiceImpl`：提供 Derby 嵌入式数据源——使用 Apache Derby 嵌入式数据库（单机模式，`jdbc:derby:${nacos.home}/data/derby-data`）

**四、配置加密**

敏感配置（如数据库密码）可通过 SPI 加密插件加密存储：
- `ConfigEncryptionPluginService`（plugin/config/src/main/java/com/alibaba/nacos/plugin/config/ConfigEncryptionPluginService.java）：加密插件 SPI 接口
- 加密后 `content` 字段存储密文，`encryptedDataKey` 字段存储加密数据密钥
- 客户端拉取配置时，SDK 自动解密——对客户端透明

**【trade-off 分析】**

ConfigInfo/HisConfigInfo 配置数据模型涉及以下关键设计权衡：

1. **快照 + 增量历史 vs 事件溯源**：Nacos 选择「当前快照 + 增量历史」模型（`ConfigInfo` 存储最新版本 + `HisConfigInfo` 记录每次变更），而非完整的 event sourcing（每次变更存储为一个不可变事件）。前者的优势是查询最新配置直接读取 `ConfigInfo`（O(1)），不需要重放所有历史事件——适合高频读取场景。但代价是配置回滚需要找到历史快照（`HisConfigInfo` 中查找目标版本），而非简单的"回退 N 个事件"。

2. **历史记录保留 vs 存储开销**：`HisConfigInfo` 记录了每次配置变更的完整历史——这对于审计追溯和配置回滚至关重要。但代价是存储开销——如果某配置项每天变更数百次，一个月就会累积数千条历史记录。Nacos 默认保留 30 天历史记录，超期自动清理——在存储开销和追溯能力之间取得了平衡。

3. **配置加密的复杂度 vs 安全性**：Nacos 通过 SPI 插件支持配置加密（`ConfigEncryptionPluginService`）。加密配置的 `content` 字段存储密文，客户端拉取时自动解密——对客户端透明。但代价是密钥管理的复杂度——`encryptedDataKey` 需要安全管理（KMS 集成或本地密钥文件），且加密/解密操作增加了 CPU 开销（每次配置发布和拉取都需要 AES 加解密）。对于非敏感配置（如公共开关配置），可以配置 `encryptedDataKey = null` 跳过加密——在安全性和性能之间按需选择。

**五、HistoryConfigCleaner：历史版本定时清理**

`HistoryConfigCleaner`（config/src/main/java/com/alibaba/nacos/config/server/service/dump/HistoryConfigCleaner.java:23-28）是 Config 模块内的清理接口（定义 `cleanHistoryConfig()` 方法），实际清理逻辑由实现类 `DefaultHistoryConfigCleaner`（service/dump/DefaultHistoryConfigCleaner.java）执行——定时扫描并删除超过保留期的历史记录（默认每天凌晨 3 点执行）：

```java
// DefaultHistoryConfigCleaner.cleanHistoryConfig()（简化核心逻辑）
public void cleanHistoryConfig() {
    // 删除超过保留期（默认 30 天）的历史记录
    long retentionMillis = getRetentionDays() * 24L * 60L * 60L * 1000L;
    hisConfigInfoMapper.removeConfigHistory(TimeUtils.getCurrentTime() - retentionMillis, 1);
}
```

清理策略：
- **默认保留 30 天**：`nacos.config.retention.days = 30`（PropertiesConstant.java:66）——可根据存储容量调整（存储充足的场景可增大到 90 天）
- **物理删除**：不是标记软删除再批量清理，而是直接 `DELETE` SQL——避免历史记录表膨胀
- **凌晨 3 点执行**：选择业务低峰期执行，减少对正常配置查询的影响（尽管是独立定时任务线程池）

**【设计模式分析】**

1. **快照模式（Snapshot Pattern）**：`ConfigInfo` 相当于当前版本的"快照"，`HisConfigInfo` 记录每次变更的增量历史。这种「快照 + 增量历史」的设计，使得配置回溯只需找到历史快照即可恢复，无需从头重建。

2. **策略模式（Strategy Pattern）**：`DataSourceService` 接口定义了数据访问策略，`ExternalDataSourceServiceImpl`（MySQL 策略）和 `LocalDataSourceServiceImpl`（Derby 策略）分别实现。`DynamicDataSource` 单例按 `isEmbeddedStorage()` 静态标志选择实现，根据 `StorageConfiguration` 条件注解在运行时确定具体策略——这是策略模式的实践。

3. **命令模式（Command Pattern）**：每次配置发布/更新操作对应一个 `ConfigChangeEvent` 命令，`NotifyCenter.publishEvent()` 发布命令，`AsyncNotifyService` 异步执行命令（向集群其他节点发送 HTTP 通知）。这种设计使得配置发布操作和通知逻辑完全解耦。

**【小结】**

Nacos 2.5.3 的配置数据模型通过「ConfigInfo（当前版本）+ HisConfigInfo（历史版本链）」双模型设计，实现了配置变更历史追溯和一键回滚能力。2.5.3 将持久化迁移到独立的 `persistence/` 模块，进一步强化了存储层的模块化和可替换性。

## 1.13 NotifyCenter 事件驱动架构：EventPublisher + Subscriber 注册机制

**【设计背景】**

Nacos 2.5.3 内部模块间通信的核心机制是 `NotifyCenter`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java）事件驱动架构。各模块通过 `NotifyCenter` 发布事件（Event）和订阅事件（Subscriber），实现模块间的完全解耦通信。例如：Config 模块发布 `ConfigDataChangeEvent` 事件，Naming 模块中的 `AsyncNotifyService` 订阅此事件并异步通知集群其他节点；Naming 模块发布 `ServiceChangedEvent`（ServiceEvent.ServiceChangedEvent，naming/src/main/java/com/alibaba/nacos/naming/core/v2/event/service/ServiceEvent.java）事件，`NamingSubscriberServiceV2Impl` 订阅此事件并通过 gRPC Bi-directional Stream 推送客户端。`NotifyCenter` 是 Nacos 内部事件总线的核心。

**【核心类关系图】**

<div class="dgm">
<div class="dgm-cap"><span class="no">图 1-13</span><span class="tt">NotifyCenter 事件驱动架构</span></div>
<div class="dgm-panel">
<div class="dgm-panel-head"><span class="t">NotifyCenter</span><span class="s">common/notify</span></div>
<div class="dgm-panel-body">
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">publishEvent(Event)</span></div>
<div class="dgm-box-b">
<ul class="dgm-kv">
<li>根据 Event 类型查找 Subscriber 列表</li>
<li>逐个调用 <span class="fld">Subscriber.onEvent(event)</span></li>
<li>事件经 DefaultPublisher 队列异步投递</li>
</ul>
</div>
</div>
<div class="dgm-box">
<div class="dgm-box-h"><span class="t">Subscriber 注册表</span><span class="s">Map&lt;Class&lt;? extends Event&gt;, List&lt;Subscriber&gt;&gt;</span></div>
</div>
<div class="dgm-varrow"></div>
<div class="dgm-cols dgm-cols-3">
<div class="dgm-eco" style="align-items:stretch;">
<div class="dgm-card" style="width:100%;"><div class="h"><span class="k">Event</span><span class="t">ConfigDataChangeEvent</span></div><ul><li>dataId</li><li>groupId</li></ul></div>
<div class="dgm-varrow"></div>
<div class="dgm-card dgm-card--deep" style="width:100%;"><div class="h"><span class="k">Subscriber</span><span class="t">AsyncNotifyService</span></div></div>
</div>
<div class="dgm-eco" style="align-items:stretch;">
<div class="dgm-card" style="width:100%;"><div class="h"><span class="k">Event</span><span class="t">ServiceChangedEvent</span></div><ul><li>service</li><li>实际事件源</li></ul></div>
<div class="dgm-varrow"></div>
<div class="dgm-card dgm-card--deep" style="width:100%;"><div class="h"><span class="k">Subscriber</span><span class="t">NamingSubscriberServiceV2Impl</span></div></div>
</div>
<div class="dgm-eco" style="align-items:stretch;">
<div class="dgm-card" style="width:100%;"><div class="h"><span class="k">Event</span><span class="t">ConnectionEvent</span></div><ul><li>connectionId</li><li>eventType</li></ul></div>
<div class="dgm-varrow"></div>
<div class="dgm-card dgm-card--deep" style="width:100%;"><div class="h"><span class="k">Subscriber</span><span class="t">ConnectionEventListener</span></div></div>
</div>
</div>
</div>
</div>
</div>

**【源码走读】**

**一、NotifyCenter 核心机制**

`NotifyCenter`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java:1-381）内部维护 `Map<String, EventPublisher>` 发布者注册表。核心方法：

```java
// NotifyCenter.publishEvent()（common/.../notify/NotifyCenter.java:276-281）
public static boolean publishEvent(final Event event) {
    try {
        return publishEvent(event.getClass(), event);
    } catch (Throwable ex) {
        LOGGER.error("There was an exception to the message publishing : ", ex);
        return false;
    }
}
// private static boolean publishEvent(Class<? extends Event>, Event)（:291-310）
// 根据 eventType 查找 publisherMap 中的 EventPublisher，调用 publisher.publish(event)
```

注册 Subscriber（`NotifyCenter.java:160-161`）：
```java
public static void registerSubscriber(final Subscriber consumer) {
    registerSubscriber(consumer, DEFAULT_PUBLISHER_FACTORY);
}
// registerSubscriber(Subscriber, EventPublisherFactory)（:171-201）
// 如果 consumer 是 SmartSubscriber，遍历 subscribeTypes() 逐个注册
```

注销 Subscriber（`NotifyCenter.java:224-246`）：
```java
public static void deregisterSubscriber(final Subscriber consumer) {
    // SmartSubscriber: 遍历 subscribeTypes() 逐个从 publisher 中注销
    // 普通 Subscriber: 从对应 topic 的 EventPublisher 中 removeSubscriber
}
```

**二、Event 类型体系**

Nacos 2.5.3 中的核心 Event 类型：

| Event 类型 | 发布者 | Subscriber | 触发时机 |
|-----------|--------|-----------|---------|
| `ConfigDataChangeEvent` | `ConfigChangePublisher.notifyConfigChange` | `AsyncNotifyService` | 配置发布/更新后 |
| `ServiceChangedEvent`（ServiceEvent 内嵌） | 服务实例变更处理链路（如 `ClientOperationEvent` 消费方） | `NamingSubscriberServiceV2Impl` | 服务实例注册/注销/健康状态变更 |
| `ClientEvent.ClientChangedEvent` | `ClientManager`（连接注册/变更时触发） | `NamingSubscriberServiceV2Impl` 等订阅方 | 客户端建立 gRPC 连接 / 订阅变更 |
| `ClientDisconnectEvent` | `ClientManager`（连接断开时触发） | 订阅方（清理失效 Client） | 客户端断开 gRPC 连接 |
| `LocalDataChangeEvent` | `ConfigCacheService`（config 模块，配置落盘刷新 MD5 后发布） | `LongPollingService`（HTTP 长轮询唤醒）、`RpcConfigChangeNotifier`（gRPC 推送） | 配置 dump 完成后本地客户端感知变更 |

**三、发布模式：默认异步队列**

`NotifyCenter.publishEvent(event)` 统一入口，默认经事件发布者异步投递：
- `publishEvent(event)`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java:276-307）：根据事件类型查找 `publisherMap` 中对应的 `EventPublisher`
- `DefaultPublisher.publish(event)`：将事件放入内存事件队列（`EventQueue`），由独立的发布线程异步逐个调用 Subscriber 的 `onEvent()`，发布者立即返回

Nacos 不存在名为 `FastNotifyCenter` 的类——默认的 `DefaultPublisher` 即通过队列实现异步发布，避免事件处理阻塞核心业务逻辑。

**四、Subscriber 注册机制**

各模块在启动阶段通过 `@PostConstruct` 方法注册自己的 Subscriber：
```java
@PostConstruct
public void init() {
    NotifyCenter.registerSubscriber(new AsyncNotifyService(), ConfigDataChangeEvent.class);
}
```

这种注册机制使得新增模块只需注册自己的 Subscriber 即可接入事件驱动架构，无需修改发布者代码——实现了模块间的完全解耦。

**五、事件驱动架构的优势**

1. **模块解耦**：Config 模块发布 `ConfigDataChangeEvent` 时不需要知道 `AsyncNotifyService` 的存在——`NotifyCenter` 负责事件路由
2. **扩展性**：新增功能只需注册新的 Subscriber 即可监听已有事件，无需修改发布者代码
3. **异步处理**：`DefaultPublisher` 事件队列异步发布，避免事件处理阻塞核心业务逻辑
4. **可观测性**：所有事件发布/订阅都可通过 `NotifyCenter` 的 Metrics 监控事件处理延迟和成功率

**【trade-off 分析】**

`NotifyCenter` 事件驱动架构涉及以下关键设计权衡：

1. **异步队列的代价**：`NotifyCenter.publishEvent()` 默认经 `DefaultPublisher` 的内存事件队列异步投递——发布线程立即返回，Subscriber 在独立的发布线程中异步消费事件（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java:276-307）。但代价是异步发布无法保证事件处理顺序（先发布的 Event A 可能晚于 Event B 被处理），且事件队列有固定长度（默认 1024），Subscriber 处理过慢时可能阻塞发布线程。`sharded` 模式将事件按主题路由到不同的 `EventPublisher` 实例，解决了部分并发瓶颈，但增加了内存消耗（每个 shard 持有独立的事件队列）。

2. **事件粒度 vs 通信开销**：Nacos 选择粗粒度事件（如 `ConfigDataChangeEvent` 代表整个配置变更，而非 `ConfigKeyAddedEvent` / `ConfigKeyDeletedEvent` 等细粒度事件）——减少了事件类型数量和注册复杂度，但代价是 Subscriber 需要自行解析事件内部的具体变更类型（新增/修改/删除）。如果改为细粒度事件，虽然 Subscriber 可以精确处理特定事件类型，但会增加 `NotifyCenter` 的注册表规模和维护成本。

3. **事件驱动 vs 直接调用**：Nacos 选择事件驱动架构而非模块间直接方法调用，换来了模块间完全解耦——Config 模块发布 `ConfigDataChangeEvent` 时不需要知道 Naming 模块的 `AsyncNotifyService` 的存在。但代价是调试复杂度增加——开发者需要追踪事件发布→订阅→处理的完整链路（跨越多个模块和线程池），而非简单的堆栈跟踪。

4. **全局单例 vs 多实例**：`NotifyCenter` 采用静态单例设计——全局唯一实例，通过 `INSTANCE.publisherMap` 管理所有 EventPublisher。这种设计简化了事件注册和发布流程（无需传递 NotifyCenter 实例），但代价是单元测试困难——无法为不同测试用例创建独立的事件总线实例，测试用例间可能意外共享事件订阅导致测试隔离问题。

**【设计模式分析】**

1. **观察者模式（Observer Pattern）**：`NotifyCenter` 是经典的观察者模式实现——`EventPublisher`（主题/被观察者）发布 Event，`Subscriber`（观察者）订阅并响应 Event。`NotifyCenter` 作为中介者负责事件路由和解耦。

2. **中介者模式（Mediator Pattern）**：`NotifyCenter` 作为各模块间通信的中介者——模块间不直接通信，而是通过 `NotifyCenter` 发布和订阅 Event。这种设计避免了模块间的网状依赖，转为星型依赖（所有模块只依赖 `NotifyCenter`）。

3. **发布-订阅模式（Pub-Sub Pattern）**：`NotifyCenter` 的 `publisherMap`（`Map<String, EventPublisher>`，`NotifyCenter.java:148`）实现了基于事件类型的发布-订阅——每个 Event 类型对应一个 `EventPublisher`，发布者不需要知道 Subscriber 的存在。

**【小结】**

`NotifyCenter`（common/src/main/java/com/alibaba/nacos/common/notify/NotifyCenter.java:1-381）是 Nacos 2.5.3 内部模块间通信的核心机制——通过 `publishEvent()`（:276）和 `registerSubscriber()`（:160）实现 Event 发布/订阅的完全解耦。各模块只需注册自己的 Subscriber 即可接入事件驱动架构，新增功能无需修改发布者代码。`publishEvent()` 默认经 `DefaultPublisher` 事件队列异步投递，避免了事件处理阻塞核心业务逻辑。
