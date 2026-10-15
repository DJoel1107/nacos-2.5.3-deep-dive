# 第6章：Nacos 2.5.3 persistence 持久化层深度分析

### 6.1.1 设计背景

Nacos 2.5.3 将持久化层从 `config` 模块中独立抽取为 `persistence/` 独立模块（72 个 Java 文件——37 个主代码 + 35 个测试），这是 2.5.x 相比 2.2.x 最重大的架构变更之一。在 2.2.x 中，数据库操作散落在 `config` 模块的 `ExternalDataSourceServiceImpl` 和嵌入式 Derby 相关类中，缺乏统一的数据源抽象和 SQL 构造规范。2.5.3 的 `persistence/` 模块提供：

1. **统一数据源抽象**：`DataSourceService` 接口定义 `JdbcTemplate`、`TransactionTemplate`、健康检查等核心能力，`LocalDataSourceServiceImpl`（嵌入式 Derby）和 `ExternalDataSourceServiceImpl`（外部 MySQL）两种实现。
2. **条件选择机制**：`DatasourceConfiguration`（`ApplicationContextInitializer`）在容器启动前读取 `platform` 配置置位静态标志——`ConditionOnEmbeddedStorage` 等 `Condition` 实现类据此判断——`DynamicDataSource` 按标志选择嵌入式或外部存储实现。
3. **SQL 构造模型**：`ModifyRequest`/`SelectRequest`/`QueryType` 提供 SQL + 参数数组的可序列化构造模型。
4. **分页助手**：`EmbeddedPaginationHelperImpl`（嵌入式 Derby 分页）和 `ExternalStoragePaginationHelperImpl`（外部 MySQL 分页）。
5. **事件体系**：`DerbyImportEvent`/`DerbyLoadEvent`/`RaftDbErrorEvent` 支持 CP 一致性快照的导入导出。

本章聚焦 `persistence/` 模块的核心类走读，涵盖数据源抽象、条件注入、SQL 构造、嵌入式存储（Derby）、外部存储（MySQL）、分页机制、事件体系与监控。

### 6.1.2 核心类关系图

图 6-1 展示了 `persistence/` 模块的顶层架构——`DataSourceService` 接口及其两大实现（`LocalDataSourceServiceImpl`/`ExternalDataSourceServiceImpl`），`DatasourceConfiguration` 通过静态标志 + `Condition` 实现类选择实现，`PaginationHelper` 分页抽象，`ModifyRequest`/`SelectRequest` SQL 构造模型：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">persistence/ 模块顶层架构</span></div><div class="dgm-box-b"><div class="dgm-box"><div class="dgm-box-h"><span class="t">DatasourceConfiguration</span><span class="s">ApplicationContextInitializer</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">读 platform → 置静态标志 useExternalDB/embeddedStorage</div><div class="dgm-note" style="border:none;background:none;padding:0;">ConditionOnEmbeddedStorage → matches(): isEmbeddedStorage()</div><div class="dgm-note" style="border:none;background:none;padding:0;">ConditionDistributedEmbedStorage / ConditionStandaloneEmbedStorage</div><div class="dgm-note" style="border:none;background:none;padding:0;">DynamicDataSource 按 isEmbeddedStorage() 手动选择实现</div></div></div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">&lt;&lt;interface&gt;&gt; DataSourceService</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">init()</span><span class="typ">: void</span></li></ul><ul class="dgm-kv"><li><span class="fld">reload()</span><span class="typ">: void</span></li></ul><ul class="dgm-kv"><li><span class="fld">checkMasterWritable()</span><span class="typ">: boolean</span></li></ul><ul class="dgm-kv"><li><span class="fld">getJdbcTemplate()</span><span class="typ">: JdbcTemplate</span></li></ul><ul class="dgm-kv"><li><span class="fld">getTransactionTemplate()</span><span class="typ">: TransactionTemplate</span></li></ul><ul class="dgm-kv"><li><span class="fld">getCurrentDbUrl()</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">getHealth()</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">getDataSourceType()</span><span class="typ">: String</span></li></ul></div></div><div class="dgm-note">△                              △</div><div class="dgm-box"><div class="dgm-box-h"><span class="t">LocalDataSource</span><span class="s">ServiceImpl</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">(Derby 嵌入式)</div><ul class="dgm-kv"><li><span class="fld">init()</span><span class="typ">: 初始化</span></li><li><span class="fld">reload()</span><span class="typ">: 重载 derby-schema.sql</span></li><li><span class="fld">getHealth()</span><span class="typ">: 返回 healthStatus 字段</span></li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">PaginationHelper&lt;E&gt; (interface)</div><div class="dgm-note" style="border:none;background:none;padding:0;">fetchPage × 2 / fetchPageLimit × 4</div><div class="dgm-note" style="border:none;background:none;padding:0;">updateLimit</div><div class="dgm-note" style="border:none;background:none;padding:0;">△</div><div class="dgm-note" style="border:none;background:none;padding:0;">EmbeddedPagination</div><div class="dgm-note" style="border:none;background:none;padding:0;">HelperImpl</div><div class="dgm-note" style="border:none;background:none;padding:0;">(持有 DatabaseOperate)</div></div></div><div class="dgm-note">SQL 构造模型:</div><div class="dgm-box"><div class="dgm-box-h"><span class="t">ModifyRequest → sql + args + rollBackOnUpdateFail</span><span class="s">SelectRequest → queryType(byte) + sql + args + className</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">QueryType → 常量类（byte 常量 0-5，对应 JdbcTemplate 方法）</div></div></div></div>

### 6.1.3 源码走读

#### 6.1.3.1 模块边界与依赖

`persistence/` 模块位于 `pom.xml` 中声明为独立 Maven 模块，不依赖 `naming`/`config`/`core` 等业务模块。模块内部除依赖 Spring JDBC（`spring-jdbc`）、HikariCP（连接池）、Derby（嵌入式数据库）和 MySQL Connector（外部存储驱动）外——还依赖 `nacos-sys`（`EnvUtil` 环境工具）、`nacos-consistency`、`nacos-datasource-plugin`（方言 SQL 生成）以及 `micrometer-core`（指标采集）——见 `persistence/pom.xml:33-70`。

`DataSourceService`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DataSourceService.java:30-87`）定义持久化层的统一契约——`init()` 初始化数据源、`getJdbcTemplate()` 获取 Spring `JdbcTemplate`、`getTransactionTemplate()` 获取事务模板、`getHealth()` 健康检查、`reload()` 重载配置。

`DynamicDataSource`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DynamicDataSource.java:26-64`）并非 Spring `AbstractRoutingDataSource` 的子类——而是一个普通单例（私有构造 + `INSTANCE` 静态字段）：`getDataSource()`（`:40-62`）按 `DatasourceConfiguration.isEmbeddedStorage()` 静态标志在 `LocalDataSourceServiceImpl`（嵌入式 Derby）与 `ExternalDataSourceServiceImpl`（外部 MySQL）之间二选一——首次调用时惰性创建并调用 `init()`——之后返回同一实例。它不涉及 `LookupKey` 上下文，也不存在读写分离的主从数据源路由。

### 6.1.4 设计模式分析

1. **策略模式（Strategy）**：`DataSourceService` 接口（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DataSourceService.java:30-87`）定义统一契约——`init()`/`reload()`/`getHealth()`/`getJdbcTemplate()`/`getTransactionTemplate()`。`LocalDataSourceServiceImpl`（嵌入式 Derby）和 `ExternalDataSourceServiceImpl`（外部 MySQL + HikariCP）两种策略实现——选择逻辑不在 Spring 条件注解中，而是由 `DatasourceConfiguration`（`persistence/configuration/DatasourceConfiguration.java:30-89`，实现 `ApplicationContextInitializer`）在容器启动前读取 `platform` 配置置位静态标志 `useExternalDB`/`embeddedStorage`——`DynamicDataSource` 再按标志手动选择实现。切换数据库仅需修改 `spring.sql.init.platform`（或旧键 `spring.datasource.platform`）配置项——无需修改任何 Java 代码。

2. **接口抽象模式（Interface Abstraction）**：`PaginationHelper<E>` 是接口（`persistence/repository/PaginationHelper.java:29-50`）——仅定义 `fetchPage()`×2、`fetchPageLimit()`×4 与 `updateLimit()` 分页契约——`EmbeddedPaginationHelperImpl`（嵌入式 Derby）和 `ExternalStoragePaginationHelperImpl`（外部 MySQL）各自实现该接口——方言分页 SQL 由 `nacos-datasource-plugin` 的 Mapper 生成后透传执行，实现类内部不拼接分页子句。

3. **条件选择模式（Conditional Selection）**：`ConditionOnEmbeddedStorage`/`ConditionOnExternalStorage`/`ConditionDistributedEmbedStorage`/`ConditionStandaloneEmbedStorage` 是四个普通 Spring `Condition` 实现类（`persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35` 等）——而非 `@Conditional` 组合注解——其 `matches()` 仅读取 `DatasourceConfiguration` 的静态标志（`isEmbeddedStorage()`/`isUseExternalDB()` 及 standalone 判断）——静态标志由 `ApplicationContextInitializer` 在容器刷新前根据 `platform` 配置置定。新增部署模式仅需新增一个 `Condition` 实现类 + 对应的 `@Conditional` 引用点。

### 6.1.5 Trade-off 分析

**表 6.1：persistence 模块独立化架构 trade-off**

| 权衡维度 | 独立 persistence 模块（2.5.3） | 散落在 config 模块（2.2.x） | 完全分离为独立 Git 仓库 |
|---------|-----------------------------|---------------------------|--------------------------|
| **模块边界** | ✅ 清晰独立——`persistence/` 零依赖 `config`/`naming`/`core` | ❌ 与 Config 业务耦合——数据库操作散落各处 | ✅ 完全物理隔离——独立版本管理 |
| **数据源抽象** | ✅ `DataSourceService` 统一契约——`LocalDataSourceServiceImpl` + `ExternalDataSourceServiceImpl` | ❌ 无统一抽象——每个 DAO 各自管理 `DataSource` | ✅ 可独立定义更强抽象 |
| **SQL 构造** | ✅ `ModifyRequest`/`SelectRequest` SQL 构造模型——SQL + 参数化绑定，杜绝 SQL 注入 | ❌ 拼字符串 SQL——SQL 注入风险 + 维护困难 | ✅ 可独立演进 SQL DSL |
| **条件注入** | ✅ `@Condition` 自动选择实现——修改配置即可切换数据库 | ❌ 手动 `if/else` 判断——切换数据库需修改代码 | ✅ 可独立设计更灵活的条件注入 |
| **测试覆盖** | ✅ 35 个测试文件——`persistence/src/test/` 独立测试 | ❌ 分散在各业务模块测试中——测试不集中 | ✅ 独立测试仓库——CI/CD 独立运行 |
| **版本管理** | ✅ 与 Nacos 主仓库统一版本——`<version>2.5.3</version>` | ❌ 版本与 Config 模块耦合 | ⚠️ 需独立版本管理 + 跨仓库依赖协调 |

Nacos 2.5.3 选择独立 Maven 模块而非完全分离 Git 仓库：`persistence/` 仍需依赖 `common` 模块（`NacosServiceLoader`/`NotifyCenter`/`EnvUtil`）——完全分离需复制 `common` 模块导致版本分裂。独立 Maven 模块在保持统一版本管理前提下获得模块边界清晰、独立测试、零业务依赖三重收益。代价是 `persistence/` 需跟随 Nacos 主版本发布节奏——无法独立发布 hotfix。

### 6.1.6 小结

Nacos 2.5.3 将持久化层从 `config` 模块独立抽取为 `persistence/` 独立 Maven 模块（72 个 Java 文件：37 主代码 + 35 测试）——提供 `DataSourceService` 统一数据源抽象（`persistence/datasource/DataSourceService.java:30-87`）、四个 `Condition` 实现类（`persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35` 等）、`PaginationHelper<E>` 分页接口（`persistence/repository/PaginationHelper.java:29-50`）、`ModifyRequest`/`SelectRequest` SQL 构造模型（`persistence/repository/embedded/sql/ModifyRequest.java:28-83`）。`LocalDataSourceServiceImpl`（嵌入式 Derby，`persistence/datasource/LocalDataSourceServiceImpl.java:52-270`）和 `ExternalDataSourceServiceImpl`（外部 MySQL + HikariCP，`persistence/datasource/ExternalDataSourceServiceImpl.java:50-306`）两种策略实现——通过 `DatasourceConfiguration`（`persistence/configuration/DatasourceConfiguration.java:30-89`，`ApplicationContextInitializer`）在容器启动前置位静态标志——覆盖单机/集群嵌入式/集群外部库三种部署模式。
### 6.2.1 设计背景

`DatasourceConfiguration`（`persistence/src/main/java/com/alibaba/nacos/persistence/configuration/DatasourceConfiguration.java:30-89`）是 `persistence/` 模块的配置入口——但它既不是 `@Configuration` 配置类，也不定义任何 `@Bean` 方法——而是实现 Spring 的 `ApplicationContextInitializer<ConfigurableApplicationContext>`。它在 Spring 容器刷新前的极早期阶段被回调——`initialize()`（`:85-88`）调用 `loadDatasourceConfiguration()`（`:58-83`）读取数据源平台配置并置位两个静态标志——`useExternalDB` 与 `embeddedStorage`（后者初值取 `EnvUtil.getStandaloneMode()`，`:40`）。选择机制分三步：

1. **置标志**：`loadDatasourceConfiguration()` 经 `DatasourcePlatformUtil.getDatasourcePlatform("")` 读取 `spring.sql.init.platform`（旧键 `spring.datasource.platform` 兜底）——平台非空且非 `derby`（如 `mysql`）→ `useExternalDB=true`；否则进入嵌入式分支——`embeddedStorage` 在 standalone 初值基础上叠加 `-DembeddedStorage=true` 系统属性——若最终未开启嵌入式存储则自动升级为 `useExternalDB=true`（`:71-81`，集群模式下 platform 为空或 derby 时自动切外部数据源的兼容逻辑）。
2. **读标志**：四个普通 `Condition` 实现类（非注解）评估静态标志——`ConditionOnEmbeddedStorage.matches()` 仅返回 `DatasourceConfiguration.isEmbeddedStorage()`（`persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35`）；`ConditionDistributedEmbedStorage` 为 `isEmbeddedStorage() && !getStandaloneMode()`（集群 + 嵌入式 JRaft 场景）；`ConditionStandaloneEmbedStorage` 为 `isEmbeddedStorage() && getStandaloneMode()`；`ConditionOnExternalStorage` 对应外部数据库分支。
3. **选实现**：`DynamicDataSource.getInstance().getDataSource()`（`DynamicDataSource.java:40-62`）按 `isEmbeddedStorage()` 手动 `new LocalDataSourceServiceImpl` 或 `new ExternalDataSourceServiceImpl` 并调用 `init()`——两个 `ServiceImpl` 均无 `@Service`/`@Conditional` 注解，不走 Spring Bean 装配；`Condition` 类则被 `@Conditional` 引用（如 `StandaloneDatabaseOperateImpl.java:53` 的 `@Conditional(ConditionStandaloneEmbedStorage.class)`）。

### 6.2.2 核心类关系图

图 6-2 展示了 `DatasourceConfiguration` 通过静态标志 + `Condition` 实现类选择数据源实现的机制：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">DatasourceConfiguration</span><span class="s">implements ApplicationContextInitializer</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">initialize() → loadDatasourceConfiguration()</div><div class="dgm-note" style="border:none;background:none;padding:0;">读 platform（spring.sql.init.platform → spring.datasource.platform）</div><div class="dgm-note" style="border:none;background:none;padding:0;">静态标志: useExternalDB / embeddedStorage(初值 = standalone)</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">Condition 实现类映射表</span><span class="s">matches() 读静态标志</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">platform 非空且非 derby → useExternalDB=true</div><div class="dgm-note" style="border:none;background:none;padding:0;">platform 空/derby + standalone → embeddedStorage=true</div><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage()          → ConditionOnEmbeddedStorage</div><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage()+standalone → ConditionStandaloneEmbedStorage</div><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage()+!standalone→ ConditionDistributedEmbedStorage</div><div class="dgm-note" style="border:none;background:none;padding:0;">!useExternalDB=false 分支     → ConditionOnExternalStorage</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">DynamicDataSource (单例)</span><span class="s">getDataSource() 惰性选择</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage()=true  → new LocalDataSourceServiceImpl().init()</div><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage()=false → new ExternalDataSourceServiceImpl().init()</div></div></div></div>

### 6.2.3 源码走读

#### 6.2.3.1 DatasourceConfiguration

`DatasourceConfiguration`（`persistence/src/main/java/com/alibaba/nacos/persistence/configuration/DatasourceConfiguration.java:30-89`）：

```java
public class DatasourceConfiguration implements ApplicationContextInitializer<ConfigurableApplicationContext> {
    
    // line 35-40: 两个静态标志——embeddedStorage 初值 = ${nacos.standalone}
    public static boolean useExternalDB = false;
    public static boolean embeddedStorage = EnvUtil.getStandaloneMode();
    
    // line 58-83: 容器刷新前读取 platform 配置并置位标志
    private void loadDatasourceConfiguration() {
        // 外部数据源在集群模式下默认使用
        String platform = DatasourcePlatformUtil.getDatasourcePlatform("");
        boolean useExternalStorage =
                !PersistenceConstant.EMPTY_DATASOURCE_PLATFORM.equalsIgnoreCase(platform) && !PersistenceConstant.DERBY
                        .equalsIgnoreCase(platform);
        setUseExternalDB(useExternalStorage);
        
        if (isUseExternalDB()) {
            setEmbeddedStorage(false);
        } else {
            boolean embeddedStorage = isEmbeddedStorage() || Boolean.getBoolean(PersistenceConstant.EMBEDDED_STORAGE);
            setEmbeddedStorage(embeddedStorage);
            // 若未开启嵌入式数据源存储，则自动升级为外部数据源存储（兼容集群模式 platform 为空/derby）
            if (!embeddedStorage) {
                setUseExternalDB(true);
            }
        }
    }
    
    @Override
    public void initialize(final ConfigurableApplicationContext applicationContext) {
        loadDatasourceConfiguration();
    }
}
```

#### 6.2.3.2 ConditionOnEmbeddedStorage 条件类

`ConditionOnEmbeddedStorage`（`persistence/src/main/java/com/alibaba/nacos/persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35`）是普通 `Condition` 实现类——不是 `@Conditional` 组合注解：

```java
public class ConditionOnEmbeddedStorage implements Condition {
    
    @Override
    public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
        // line 33: 仅读取 DatasourceConfiguration 静态标志
        return DatasourceConfiguration.isEmbeddedStorage();
    }
}
```

platform 的判定不在 `matches()` 中——而是在更早的 `DatasourceConfiguration.loadDatasourceConfiguration()`（经 `DatasourcePlatformUtil`，`persistence/utils/DatasourcePlatformUtil.java:36-42`）完成。**`ConditionOnExternalStorage`**（`persistence/.../condition/ConditionOnExternalStorage.java`）：同样仅读取静态标志——外部数据库分支时返回 `true`，供 `@Conditional` 引用点（如数据库操作实现类）评估。

### 6.2.4 设计模式分析

1. **条件注入模式（Conditional Injection）**：Spring `@Conditional` 机制 + 自定义 `Condition` 实现（`persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35` 等）——区别于常见做法的是：Nacos 把"配置读取"前移到 `ApplicationContextInitializer`（`DatasourceConfiguration.java:30-89`）——容器刷新前即完成静态标志置位——各 `Condition.matches()` 只做标志读取，避免条件评估阶段重复解析环境配置。`@Conditional` 引用点（如 `StandaloneDatabaseOperateImpl.java:53` 的 `@Conditional(ConditionStandaloneEmbedStorage.class)`）在 Bean 注册阶段评估——返回 `false` 时跳过对应 Bean 的创建。

2. **工厂模式（Factory）**：`DynamicDataSource`（`persistence/.../datasource/DynamicDataSource.java:26-64`）作为单例工厂——按 `isEmbeddedStorage()` 标志手动 `new` 出 `LocalDataSourceServiceImpl` 或 `ExternalDataSourceServiceImpl` 并惰性调用 `init()`。两个 `ServiceImpl` 不是 Spring Bean——调用方（如 `StandaloneDatabaseOperateImpl` 的 `@PostConstruct`）通过 `DynamicDataSource.getInstance().getDataSource()` 获取——工厂封装了具体实现的创建与初始化时序。

3. **策略模式（Strategy）**：`DataSourceService` 接口（`persistence/datasource/DataSourceService.java:30-87`）定义统一契约——`init()`/`reload()`/`getHealth()`/`getJdbcTemplate()`/`getTransactionTemplate()`——`LocalDataSourceServiceImpl`（嵌入式 Derby）和 `ExternalDataSourceServiceImpl`（外部 MySQL + HikariCP）两种策略实现——切换部署模式仅需修改 `spring.sql.init.platform`（或旧键 `spring.datasource.platform`）配置项——符合开闭原则（Open-Closed Principle）——对扩展开放——对修改关闭。

### 6.2.5 Trade-off 分析

**表 6.2：静态标志 + Condition vs 手动切换 trade-off**

| 权衡维度 | ApplicationContextInitializer + Condition（Nacos 2.5.3 选择） | 手动 if/else 切换 | Spring Profiles |
|---------|---------------------|-------------------|----------------|
| **扩展性** | ✅ 新增部署模式只需新增 Condition 实现类 + `@Conditional` 引用——无需修改 `DatasourceConfiguration.java:30-89` 标志逻辑 | ❌ 需修改所有切换判断点——改动散落各处 | ⚠️ 新增 `application-{profile}.properties` |
| **配置灵活性** | ✅ 通过 `spring.sql.init.platform`（旧键 `spring.datasource.platform` 兜底）配置切换——零代码改动 | ❌ 需修改代码硬编码 `if/else` 分支 | ✅ 通过 `spring.profiles.active` 配置切换 |
| **时序确定性** | ✅ 标志在容器刷新前置位——条件评估阶段（`matches()`）读静态标志零开销、结果确定 | ❌ 运行时逐点判断——各处时序不一致 | ⚠️ Profile 依赖 Environment 就绪时机 |
| **复合条件** | ✅ `Condition` 实现类可组合静态标志（如 `isEmbeddedStorage() && !getStandaloneMode()`）表达复合场景 | ❌ 手动嵌套 `if/else`——可读性差 | ❌ 单一 `spring.profiles.active` 值——无法表达复合条件 |
| **可读性** | ✅ 条件类名称自文档化（`ConditionOnEmbeddedStorage` 明确表达意图） | ❌ `if/else` 散落各处——需阅读所有工厂方法 | ⚠️ Profile 命名需约定规范（无编译期检查） |
| **编译期安全** | ✅ 条件在 Spring 容器启动时评估——`matches()=false` 时不创建 Bean | ❌ 运行时 `if/else` 判断——编译期零安全保障 | ✅ 同 `@Conditional` 机制 |

Nacos 2.5.3 选择 `ApplicationContextInitializer` + 静态标志而非 Spring Profiles：数据源选择必须在容器刷新前确定（`LocalDataSourceServiceImpl` 等类在非 Bean 上下文中被手动创建）——`ApplicationContextInitializer` 恰好提供这一极早回调时机。`DatasourceConfiguration`（`:30-89`）将 platform 解析逻辑集中在一处——`Condition` 实现类只做标志读取——条件逻辑与标志置定物理分离——修改条件逻辑无需触碰配置解析代码。

### 6.2.6 小结

`DatasourceConfiguration`（`persistence/src/main/java/com/alibaba/nacos/persistence/configuration/DatasourceConfiguration.java:30-89`）实现 `ApplicationContextInitializer`——容器刷新前经 `loadDatasourceConfiguration()` 读取 `spring.sql.init.platform`（由 `DatasourcePlatformUtil.getDatasourcePlatform()`，`persistence/utils/DatasourcePlatformUtil.java:36-42` 读取，旧键 `spring.datasource.platform` 兜底）并置位静态标志 `useExternalDB`/`embeddedStorage`——集群模式下 platform 为空或 derby 时自动升级为外部数据源（`:71-81`）。四个 `Condition` 实现类——`ConditionOnEmbeddedStorage`（`persistence/configuration/condition/ConditionOnEmbeddedStorage.java:29-35`，仅返回 `isEmbeddedStorage()`）/`ConditionOnExternalStorage`/`ConditionDistributedEmbedStorage`（`isEmbeddedStorage() && !getStandaloneMode()`）/`ConditionStandaloneEmbedStorage`（`isEmbeddedStorage() && getStandaloneMode()`）——供 `@Conditional` 引用点评估，覆盖单机嵌入式/集群嵌入式/集群外部库三种部署模式。`DynamicDataSource`（单例）按标志手动 `new` 并初始化 `LocalDataSourceServiceImpl` 或 `ExternalDataSourceServiceImpl`——两个实现均非 Spring Bean——实现数据源选择与业务逻辑的完全解耦。


### 6.3.1 设计背景

`LocalDataSourceServiceImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java:52-270`）是 `DataSourceService` 接口的嵌入式 Derby 实现——适用于单机模式和测试环境。嵌入式 Derby 数据库存储在 `$NACOS_HOME/data/derby-data/` 目录（`PersistenceConstant.DERBY_BASE_DIR`，`PersistenceConstant.java:46`）——无需用户安装和配置独立数据库服务器——实现零配置内嵌数据库。`init()`（`:78-89`）拼接 `jdbc:derby:${nacos.home}/data/derby-data;create=true` 的 JDBC URL（`create=true`——首次启动自动创建数据库文件）——经 `DataSourcePoolProperties.build()`（`:149-155`）构建 `HikariDataSource` 连接池（驱动 `org.apache.derby.jdbc.EmbeddedDriver`、用户名/密码均为 `nacos`）——`initialize()` 末尾调用 `reload()`（`:170`）执行 DDL 建表脚本 `derby-schema.sql` 自动创建 `config_info`/`config_tags_relation`/`his_config_info` 等业务表。`getHealth()`（`:193-196`）仅返回 `healthStatus` 字段（初始 `"UP"`）——不做实时探测。`reload()`（`:91-105`）重新执行 derby-schema.sql 建表脚本——幂等地补齐缺失表结构。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过 `ThreadLocal<ArrayList<ModifyRequest>>`（`SQL_CONTEXT`）与 `ThreadLocal<Map<String, String>>`（`EXTEND_INFO_CONTEXT`）按线程累积待执行的 SQL 与扩展信息——供 `blockUpdate()` 一次性提交。`LocalDataSourceServiceImpl` 不通过 `@Conditional` 注入为 Spring Bean——而是由 `DynamicDataSource.getInstance().getDataSource()` 在 `isEmbeddedStorage()` 为 true 时惰性创建（`DynamicDataSource.java:46-51`）。

### 6.3.2 核心类关系图

图 6-3 展示了 `DataSourceService` 接口与 `DynamicDataSource` 的关系：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">&lt;&lt;interface&gt;&gt; DataSourceService</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">init()</span><span class="typ">: void</span></li></ul><ul class="dgm-kv"><li><span class="fld">reload()</span><span class="typ">: void</span></li></ul><ul class="dgm-kv"><li><span class="fld">checkMasterWritable()</span><span class="typ">: boolean</span></li></ul><ul class="dgm-kv"><li><span class="fld">getJdbcTemplate()</span><span class="typ">: JdbcTemplate</span></li></ul><ul class="dgm-kv"><li><span class="fld">getTransactionTemplate()</span><span class="typ">: TransactionTemplate</span></li></ul><ul class="dgm-kv"><li><span class="fld">getCurrentDbUrl()</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">getHealth()</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">getDataSourceType()</span><span class="typ">: String</span></li></ul></div></div><div class="dgm-note">△                              △</div><div class="dgm-box"><div class="dgm-box-b"><div class="dgm-box"><div class="dgm-box-h"><span class="t">LocalDataSource</span><span class="s">ServiceImpl</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">jdbcTemplate</div><div class="dgm-note" style="border:none;background:none;padding:0;">transactionTemplate</div><div class="dgm-note" style="border:none;background:none;padding:0;">init():</div><div class="dgm-note" style="border:none;background:none;padding:0;">HikariDataSource(Derby)</div><div class="dgm-note" style="border:none;background:none;padding:0;">reload():</div><div class="dgm-note" style="border:none;background:none;padding:0;">重执行 derby-schema.sql</div><div class="dgm-note" style="border:none;background:none;padding:0;">getHealth():</div><div class="dgm-note" style="border:none;background:none;padding:0;">返回 healthStatus 字段</div></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">DynamicDataSource</span><span class="s">普通单例（私有构造 + INSTANCE）</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">getDataSource():</div><div class="dgm-note" style="border:none;background:none;padding:0;">isEmbeddedStorage() ?</div><div class="dgm-note" style="border:none;background:none;padding:0;">new LocalDataSourceServiceImpl</div><div class="dgm-note" style="border:none;background:none;padding:0;">: new ExternalDataSourceServiceImpl</div><div class="dgm-note" style="border:none;background:none;padding:0;">惰性创建 + init()</div></div></div></div></div></div>

### 6.3.3 源码走读

#### 6.3.3.1 DataSourceService 接口

`DataSourceService`（`persistence/.../datasource/DataSourceService.java:30-87`）定义统一数据源抽象：

- `init()`：初始化数据源（Derby 嵌入式 or HikariCP 连接池）
- `reload()`：重载（Derby 实现为重新执行 derby-schema.sql；外部实现为重建连接池列表）
- `checkMasterWritable()`：检查主库是否可写（外部 MySQL 场景查询 `@@read_only`；Derby 实现恒返回 `true`）
- `getJdbcTemplate()`：获取 Spring `JdbcTemplate`（SQL 执行入口）
- `getTransactionTemplate()`：获取事务模板（声明式事务管理）
- `getCurrentDbUrl()`：获取当前数据库 JDBC URL
- `getHealth()`：健康状态（Derby 实现返回 `healthStatus` 字段；外部实现返回 `CheckDbHealthTask` 维护的结果）
- `getDataSourceType()`：获取数据源类型（"derby"/"mysql"）

#### 6.3.3.2 DynamicDataSource 动态数据源

`DynamicDataSource`（`persistence/.../datasource/DynamicDataSource.java:26-64`）是一个普通单例——并非 Spring `AbstractRoutingDataSource` 的子类：

```java
public class DynamicDataSource {
    
    private DataSourceService localDataSourceService = null;
    
    private DataSourceService basicDataSourceService = null;
    
    private static final DynamicDataSource INSTANCE = new DynamicDataSource();

    private DynamicDataSource() {}

    public static DynamicDataSource getInstance() {
        return INSTANCE;
    }
    
    public synchronized DataSourceService getDataSource() {
        // Embedded storage is used by default in stand-alone mode
        // In cluster mode, external databases are used by default
        if (DatasourceConfiguration.isEmbeddedStorage()) {
            if (localDataSourceService == null) {
                localDataSourceService = new LocalDataSourceServiceImpl();
                localDataSourceService.init();
            }
            return localDataSourceService;
        } else {
            if (basicDataSourceService == null) {
                basicDataSourceService = new ExternalDataSourceServiceImpl();
                basicDataSourceService.init();
            }
            return basicDataSourceService;
        }
    }
}
```

`DynamicDataSource` 不持有任何 `LookupKey` 上下文，也不存在主从数据源路由——它只做一件事：按 `DatasourceConfiguration.isEmbeddedStorage()` 静态标志在 `LocalDataSourceServiceImpl`（嵌入式 Derby）与 `ExternalDataSourceServiceImpl`（外部 MySQL）之间二选一，首次调用时惰性创建并执行 `init()`，之后复用同一实例。这也正是 `LocalDataSourceServiceImpl.init()` 被触发的时机——它不实现 `InitializingBean`，初始化完全由这里的惰性调用驱动。

### 6.3.4 设计模式分析

1. **单例模式（Singleton）**：`LocalDataSourceServiceImpl` 不是 Spring Bean——而是由 `DynamicDataSource` 单例（`DynamicDataSource.java:26-64`）惰性创建并全局持有——整个 JVM 内共享同一嵌入式 Derby `HikariDataSource` 连接池实例。所有线程通过 `DynamicDataSource.getInstance().getDataSource()` 获取同一实现——`EmbeddedStorageContextHolder` 的两个 `ThreadLocal`（SQL 上下文与扩展信息上下文）保证每个线程累积独立的待执行 SQL——底层 `Connection` 由 HikariCP 连接池统一管理。

2. **工厂模式（Factory）**：`DataSourcePoolProperties.build(EnvUtil.getEnvironment())`（`DataSourcePoolProperties.java:62-66`）作为连接池配置工厂——默认值（`connectionTimeout=3s`、`validationTimeout=10s`、`idleTimeout=10min`、`maxPoolSize=20`、`minimumIdle=2`）可经 `db.pool.config.*` 配置前缀覆盖——`LocalDataSourceServiceImpl.initialize()`（`LocalDataSourceServiceImpl.java:149-155`）在其上设置 Derby 驱动、`jdbc:derby:${nacos.home}/data/derby-data;create=true` 的 JDBC URL 与用户名/密码后产出 `HikariDataSource`。工厂模式封装了连接池的构建与默认值管理——调用方只需调用 `init()` 无需了解 HikariCP 底层 API。

3. **生命周期模式（Lifecycle）**：`LocalDataSourceServiceImpl` 不实现 Spring `InitializingBean`——`init()` 由 `DynamicDataSource.getInstance().getDataSource()` 首次调用时惰性触发（`DynamicDataSource.java:46-51`），且 `initialize` 标志保证幂等。`reload()`（`LocalDataSourceServiceImpl.java:91-105`）重新执行 derby-schema.sql 建表脚本——幂等地补齐缺失的表结构（单条执行失败仅告警不中断）——而非重建数据源。

### 6.3.5 Trade-off 分析

**表 6.3：Derby vs MySQL vs H2 trade-off**

| 权衡维度 | 嵌入式 Derby（Nacos 单机/测试选择） | 外部 MySQL（Nacos 生产集群选择） | H2 嵌入式数据库 |
|---------|-------------------------------------|----------------------------------|------------------|
| **运维复杂度** | ✅ 零运维——Derby 内嵌运行，无需独立数据库服务器 | ❌ 需独立 MySQL 服务器——安装 + 配置 + 备份 + 监控 | ✅ 零运维——同 Derby |
| **并发能力** | ⚠️ Derby 单连接写入——嵌入式 Derby 仅支持单 JVM 进程内读写 | ✅ 高并发读写——HikariCP `maximumPoolSize=20` | ⚠️ H2 同单连接写入 |
| **SQL 兼容性** | ✅ Apache Derby SQL 标准——高度兼容 MySQL SQL（仅 `LIMIT`→`OFFSET...FETCH NEXT`） | ✅ MySQL SQL 原生——无需 SQL 方言适配 | ⚠️ H2 MySQL 兼容模式——`MODE=MySQL` 仍有细微差异 |
| **数据持久化** | ✅ Derby 数据库文件——`$NACOS_HOME/data/derby-data/`，重启后数据仍存在 | ✅ MySQL 磁盘存储——主从复制 + binlog 备份 | ✅ H2 文件存储——`.mv.db` 文件 |
| **启动时间** | ✅ <2s——嵌入式 Derby 无需网络连接 | ❌ 需等待 MySQL 服务器启动——首次启动 10-30s | ✅ <1s——H2 内存模式最快 |
| **License** | ✅ Apache License 2.0——与 Nacos 同属 Apache 基金会生态 | ✅ GPLv2——MySQL Community Edition | ✅ EPL 1.0 / MPL 2.0——H2 dual License |

Nacos 2.5.3 选择嵌入式 Derby 而非 H2 的核心原因：Apache Derby 与 Nacos 同属 Apache 基金会生态——License 兼容（Apache License 2.0），无需额外的 License 合规审查。Derby 的 SQL 语法与 MySQL 高度兼容——`persistence/` 模块的 `SqlTypeLimiter` 仅需适配 `LIMIT OFFSET`→`OFFSET...FETCH NEXT` 一个 SQL 方言差异——其余 DDL/DML 完全通用。H2 需要 `MODE=MySQL` 才有类似的兼容性——但仍有细微差异（如 `AUTO_INCREMENT` vs `IDENTITY`）。代价是嵌入式 Derby 的并发能力有限（单 JVM 进程内读写）——但 Nacos 单机模式通常仅服务于小规模配置管理（<100 个客户端），嵌入式 Derby 的性能完全满足需求。对于生产集群模式（>10 节点），`DatasourceConfiguration` 的静态标志使 `DynamicDataSource` 自动选择 `ExternalDataSourceServiceImpl`——使用 HikariCP 连接池连接外部 MySQL——支持高并发读写。

### 6.3.6 小结

`LocalDataSourceServiceImpl`（`persistence/datasource/LocalDataSourceServiceImpl.java:52-270`）通过 `DataSourcePoolProperties` 构建的 `HikariDataSource` 连接 Derby 嵌入式驱动（`org.apache.derby.jdbc.EmbeddedDriver`）实现零配置内嵌数据库——`init()`（:`78-89`）以 `jdbc:derby:${nacos.home}/data/derby-data;create=true` 自动创建 Derby 数据库文件，`initialize()` 末尾经 `reload()` 执行类路径 `META-INF/derby-schema.sql`（优先 `conf/derby-schema.sql`）建表脚本。`getHealth()`（:`193-196`）仅返回 `healthStatus` 字段（初始 `"UP"`）——不做实时探测。`reload()`（:`91-105`）重新执行 derby-schema.sql 建表脚本——幂等地补齐缺失表结构。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过两个 `ThreadLocal`——`SQL_CONTEXT`（`ArrayList<ModifyRequest>`）与 `EXTEND_INFO_CONTEXT`（`Map<String, String>`）——按线程累积待执行 SQL 与扩展信息，供 `blockUpdate()` 一次性提交。

`LocalDataSourceServiceImpl` 是 `DataSourceService` 的嵌入式 Derby 实现，适用于单机模式和集群嵌入式模式（`DatasourceConfiguration.isEmbeddedStorage()` 为 true 时由 `DynamicDataSource` 选择）。Derby 是 Apache 开源嵌入式 Java 数据库，无需独立安装——随 Nacos 进程启动内嵌运行，数据文件存储在 `~/nacos/data/derby-data/` 目录下。

嵌入式 Derby 的优势：零运维（无需独立数据库服务器）、零配置（开箱即用）、适合中小规模集群（<10 节点）。劣势：不支持高并发读写（单 JVM 进程内读写）、数据迁移困难（需借助 `DerbyUtils` 等工具导入导出）。

### 6.4.1 设计背景

`LocalDataSourceServiceImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java:52-270`）是 `DataSourceService` 接口的嵌入式 Derby 实现——适用于单机模式和测试环境。嵌入式 Derby 数据库存储在 `$NACOS_HOME/data/derby-data/` 目录（`PersistenceConstant.DERBY_BASE_DIR`）——无需用户安装和配置独立数据库服务器——实现零配置内嵌数据库。`LocalDataSourceServiceImpl` 不是 Spring Bean——当 `DatasourceConfiguration.isEmbeddedStorage()` 为 true 时由 `DynamicDataSource.getInstance().getDataSource()`（`DynamicDataSource.java:46-51`）惰性创建并调用 `init()`。

`init()`（`LocalDataSourceServiceImpl.java:78-89`）拼接 `jdbc:derby:${nacos.home}/data/derby-data;create=true` 的 JDBC URL——`create=true`——首次启动自动创建数据库文件——随后 `initialize()`（`:149-171`）经 `DataSourcePoolProperties.build(EnvUtil.getEnvironment())` 构建 `HikariDataSource`（驱动 `org.apache.derby.jdbc.EmbeddedDriver`、用户名/密码均为 `nacos`、`JdbcTemplate` 预设 `maxRows=50000`/`queryTimeout=5000`）——末尾调用 `reload()`（`:91-105`）执行 DDL 建表脚本 `derby-schema.sql` 自动创建 `config_info`/`config_tags_relation`/`his_config_info` 等业务表。`getHealth()`（`:193-196`）仅返回 `healthStatus` 字段（初始 `"UP"`）——`LocalDataSourceServiceImpl` 本身不执行实时健康探测。`reload()` 重新读取并逐条执行建表脚本——单条失败仅告警——实现幂等的表结构补齐。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过 `ThreadLocal<ArrayList<ModifyRequest>>`（`SQL_CONTEXT`）与 `ThreadLocal<Map<String, String>>`（`EXTEND_INFO_CONTEXT`）按线程累积待执行的 SQL 与扩展信息——供 `DatabaseOperate.blockUpdate()` 在提交时一次性取出并清理。

### 6.4.2 核心类关系图

图 6-4 展示了 `LocalDataSourceServiceImpl` 的嵌入式 Derby 初始化流程：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">LocalDataSourceServiceImpl</span><span class="s">implements DataSourceService</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li>jdbcTemplate: JdbcTemplate</li><li>transactionTemplate: TransactionTemplate</li><li>dataSource: HikariDataSource</li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">init():</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 1: jdbcUrl = jdbc:derby:${nacos.home}/data/derby-data;create=true</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 2: DataSourcePoolProperties.build() → HikariDataSource</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 3: new JdbcTemplate(maxRows=50000) + TransactionTemplate(timeout=5000)</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 4: reload() → 执行 derby-schema.sql (CREATE TABLE)</div><div class="dgm-note" style="border:none;background:none;padding:0;">reload():</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ 重新逐条执行 derby-schema.sql（幂等补齐表结构）</div><div class="dgm-note" style="border:none;background:none;padding:0;">getHealth():</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ 返回 healthStatus 字段（初始 "UP"，无实时探测）</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">Derby 嵌入式数据库</span><span class="s">数据文件: ~/nacos/data/derby-data/</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">表结构: config_info, his_config_info, users, roles,</div><div class="dgm-note" style="border:none;background:none;padding:0;">permissions, tenant_info, tenant_capacity</div><div class="dgm-note" style="border:none;background:none;padding:0;">单 JVM 进程内读写（嵌入式 Derby 限制）</div></div></div></div>

### 6.4.3 源码走读

#### 6.4.3.1 init()——嵌入式 Derby 初始化

`LocalDataSourceServiceImpl.init()`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java:78-89` 与 `:149-171`）：

```java
@Override
public synchronized void init() throws Exception {
    if (DatasourceConfiguration.isUseExternalDB()) {
        return;
    }
    if (!initialize) {
        LOGGER.info("use local db service for init");
        final String jdbcUrl = "jdbc:derby:" + Paths.get(EnvUtil.getNacosHome(), derbyBaseDir) + ";create=true";
        initialize(jdbcUrl);
        initialize = true;
    }
}

private synchronized void initialize(String jdbcUrl) {
    // line 150-155: 经 DataSourcePoolProperties 构建 HikariDataSource
    DataSourcePoolProperties poolProperties = DataSourcePoolProperties.build(EnvUtil.getEnvironment());
    poolProperties.setDriverClassName(jdbcDriverName);      // org.apache.derby.jdbc.EmbeddedDriver
    poolProperties.setJdbcUrl(jdbcUrl);                     // jdbc:derby:${nacos.home}/data/derby-data;create=true
    poolProperties.setUsername(userName);                   // nacos
    poolProperties.setPassword(password);                   // nacos
    HikariDataSource ds = poolProperties.getDataSource();
    DataSourceTransactionManager tm = new DataSourceTransactionManager();
    tm.setDataSource(ds);
    if (jdbcTemplateInit) {
        jt.setDataSource(ds);
        tjt.setTransactionManager(tm);
    } else {
        jt = new JdbcTemplate();
        jt.setMaxRows(50000);
        jt.setQueryTimeout(5000);
        jt.setDataSource(ds);
        tjt = new TransactionTemplate(tm);
        tjt.setTimeout(5000);
        jdbcTemplateInit = true;
    }
    reload();   // line 170: 执行 derby-schema.sql 建表脚本
}
```

#### 6.4.3.2 getHealth()——健康状态

`getHealth()`（`LocalDataSourceServiceImpl.java:193-196`）不做实时探测——仅返回内部维护的 `healthStatus` 字段（初始 `"UP"`，提供 `setHealthStatus()` 写入方法）：

```java
@Override
public String getHealth() {
    return healthStatus;
}
```

真实的数据库探测逻辑存在于外部数据源实现 `ExternalDataSourceServiceImpl`——由 `CheckDbHealthTask`（`:272-305`）每 10 秒定时检测各数据源并更新 `isHealthList`。

### 6.4.4 设计模式分析

1. **模板方法模式（Template Method）**：`DataSourceService` 接口（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/DataSourceService.java:30-87`）定义 `init()`/`reload()`/`getHealth()`/`getJdbcTemplate()`/`getTransactionTemplate()`/`getCurrentDbUrl()`/`getDataSourceType()` 等模板方法——`LocalDataSourceServiceImpl`（`persistence/.../datasource/LocalDataSourceServiceImpl.java:52-270`）实现嵌入式 Derby 的具体逻辑：`init()` 以 `create=true` 自动创建 Derby 数据库文件并经 `reload()` 执行 `derby-schema.sql` 建表脚本、`getHealth()` 返回 `healthStatus` 字段、`reload()` 幂等重执行建表脚本。模板方法模式使 `LocalDataSourceServiceImpl` 和 `ExternalDataSourceServiceImpl` 共享统一的接口契约——上层业务代码面向 `DataSourceService` 接口编程，无需关心底层是嵌入式 Derby 还是外部 MySQL。

2. **工厂模式（Factory）**：`DataSourcePoolProperties.build(EnvUtil.getEnvironment())` 作为连接池配置工厂——产出承载 Derby 嵌入式连接的 `HikariDataSource`——`LocalDataSourceServiceImpl.initialize()`（`LocalDataSourceServiceImpl.java:149-155`）在其上设置 Derby 驱动与 `jdbc:derby:${nacos.home}/data/derby-data;create=true` 的 JDBC URL。Derby 嵌入式数据库文件存储在 `$NACOS_HOME/data/derby-data/` 目录——单机模式下无需用户手动配置数据库 URL。

3. **上下文持有者模式（Context Holder）**：`EmbeddedStorageContextHolder`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）持有两个 `ThreadLocal`——`SQL_CONTEXT`（`ArrayList<ModifyRequest>`，按 `executeNo` 顺序累积待执行写请求）与 `EXTEND_INFO_CONTEXT`（`Map<String, String>` 扩展信息）。业务代码经 `addSqlContext()` 追加 SQL——`DatabaseOperate.blockUpdate()` 提交时一次性取出当前线程的 SQL 列表并调用 `cleanAllContext()` 清理——实现线程级的 SQL 攒批与事务聚合。

### 6.4.5 Trade-off 分析

**表 6.4：嵌入式 Derby vs 外部 MySQL trade-off**

| 权衡维度 | 嵌入式 Derby（Nacos 单机/测试选择） | 外部 MySQL（Nacos 生产集群选择） | H2 嵌入式数据库 |
|---------|-------------------------------------|----------------------------------|------------------|
| **运维复杂度** | ✅ 零运维——内嵌运行，无需独立数据库服务器 | ❌ 需独立 MySQL 服务器——安装 + 配置 + 备份 + 监控 | ✅ 零运维——同 Derby |
| **并发能力** | ⚠️ Derby 单连接写入——嵌入式 Derby 仅支持单 JVM 进程内读写 | ✅ 高并发读写——HikariCP 连接池（`maximumPoolSize=20`） | ⚠️ H2 同单连接写入 |
| **SQL 兼容性** | ✅ Apache Derby SQL 标准——高度兼容 MySQL SQL（`LIMIT`→`OFFSET...FETCH NEXT` 除外） | ✅ MySQL SQL 原生支持——无需 SQL 方言适配 | ⚠️ H2 MySQL 兼容模式——`MODE=MySQL` 但仍有细微差异 |
| **数据迁移** | ⚠️ 需 `DerbyUtils` 等工具——进程内 `dataImport` 导入/导出 | ✅ MySQL dump/import——`mysqldump`/`mysql` 标准工具 | ⚠️ H2 `SCRIPT TO`/`RUNSCRIPT FROM`——非标准工具 |
| **适用规模** | 测试/单机/小集群（<10 节点）——嵌入式 Derby 性能满足小规模配置管理 | 生产大集群（>10 节点）——MySQL 主从复制 + 读写分离 | 测试环境——H2 内存模式快速测试 |
| **启动时间** | ✅ <2s——嵌入式 Derby 无需网络连接 | ❌ 需等待 MySQL 服务器启动——首次启动 10-30s | ✅ <1s——H2 内存模式最快 |

Nacos 2.5.3 选择嵌入式 Derby 而非 H2 的核心原因：Apache Derby 是 Apache 顶级项目——与 Nacos 同属 Apache 基金会生态，License 兼容（Apache License 2.0）。Derby 的 SQL 语法与 MySQL 高度兼容——`persistence/` 模块的 `SqlTypeLimiter` 仅需适配 `LIMIT OFFSET`→`OFFSET...FETCH NEXT` 一个 SQL 方言差异——其余 DDL（`CREATE TABLE`）/DML（`INSERT`/`UPDATE`/`DELETE`）完全通用。H2 需要 `MODE=MySQL` 才有类似的兼容性——但仍有细微差异（如 `AUTO_INCREMENT` vs `IDENTITY`）。代价是嵌入式 Derby 的并发能力有限（单 JVM 进程内读写）——但 Nacos 单机模式通常仅服务于小规模配置管理（<100 个客户端），嵌入式 Derby 的性能完全满足需求。

### 6.4.6 小结

`LocalDataSourceServiceImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java:52-270`）通过 `DataSourcePoolProperties` 构建的 `HikariDataSource` 连接 Derby 嵌入式驱动实现零配置内嵌数据库——`init()`（`:78-89`）以 `jdbc:derby:${nacos.home}/data/derby-data;create=true` 自动创建 Derby 数据库文件、`reload()`（`:91-105`）执行类路径 `META-INF/derby-schema.sql`（优先 `conf/derby-schema.sql`）建表脚本、`getHealth()`（`:193-196`）仅返回 `healthStatus` 字段（初始 `"UP"`，无实时探测）。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过 `ThreadLocal<ArrayList<ModifyRequest>>` 与 `ThreadLocal<Map<String, String>>` 按线程累积待执行 SQL 与扩展信息。适用于单机/测试/小集群（<10 节点）——零运维、零配置、零外部依赖。外部 MySQL 实现参见 6.5 节。


### 6.5.1 设计背景

`ExternalDataSourceServiceImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/ExternalDataSourceServiceImpl.java:50-306`）是 `DataSourceService` 接口的外部 MySQL 实现——通过 HikariCP 连接池（`HikariDataSource`）管理 MySQL 连接，支持高并发读写。当 `DatasourceConfiguration.isUseExternalDB()` 为 true 时由 `DynamicDataSource` 选择（`DynamicDataSource.java:52-57`）——与 `ExternalStoragePaginationHelperImpl`（SQL 方言由 Mapper 生成后透传分页）配合使用。`init()`（`:87-127`）先构建多个预设超时的 `JdbcTemplate`（`maxRows=50000`、事务模板 `timeout=TRANSACTION_QUERY_TIMEOUT`）——`reload()`（`:130-170`）经 `ExternalDataSourceProperties`（`persistence/.../ExternalDataSourceProperties.java:75-98`）绑定 `db.num`/`db.url.N`/`db.user.N`/`db.password.N` 多数据源配置——驱动缺省 `com.mysql.cj.jdbc.Driver`、未显式配置校验 SQL 时设置 `connectionTestQuery="SELECT 1"`——为每个数据源创建 `HikariDataSource` 并经 `ConnectionCheckUtil.checkDataSourceConnection()` 做 fail-fast 校验；连接池参数由 `DataSourcePoolProperties` 提供默认值（`connectionTimeout=3s`、`validationTimeout=10s`、`idleTimeout=10min`、`maxPoolSize=20`、`minimumIdle=2`，可经 `db.pool.config.*` 覆盖）——数据源数量超过 `DB_MASTER_SELECT_THRESHOLD` 时调度 `SelectMasterTask`，并总是调度 `CheckDbHealthTask`（每 10 秒）。`getHealth()`（`:215-229`）基于 `CheckDbHealthTask` 维护的 `isHealthList` 返回 `UP`/`WARN:ip`/`DOWN:ip`。`DatasourceMetrics`（`persistence/.../monitor/DatasourceMetrics.java:27-34`）仅提供 `getDbException()` 返回 `Metrics.counter("nacos_exception", "module", "config", "name", "db")` 数据库异常计数器——在 `SelectMasterTask`/`CheckDbHealthTask` 中递增。

### 6.5.2 核心类关系图

图 6-5 展示了 `ExternalDataSourceServiceImpl` 通过 HikariCP 连接池管理 MySQL 连接的架构：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">ExternalDataSourceServiceImpl</span><span class="s">implements DataSourceService</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li>jdbcTemplate: JdbcTemplate</li><li>transactionTemplate: TransactionTemplate</li><li>dataSourceList: List&lt;HikariDataSource&gt;</li><li>isHealthList: List&lt;Boolean&gt;</li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">init():</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 1: 构建 JdbcTemplate(maxRows=50000) + testMasterJT 等</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 2: DataSourceTransactionManager + TransactionTemplate</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 3: isUseExternalDB() → reload()</div><div class="dgm-note" style="border:none;background:none;padding:0;">STEP 4: 调度 SelectMasterTask（超过阈值时）+ CheckDbHealthTask（每 10s）</div><div class="dgm-note" style="border:none;background:none;padding:0;">getHealth():</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ 基于 CheckDbHealthTask 维护的 isHealthList 返回 UP/WARN:ip/DOWN:ip</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">HikariDataSource × N（多数据源）</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">jdbcUrl</span><span class="typ">: 来自 db.url.N</span></li></ul><ul class="dgm-kv"><li><span class="fld">driverClassName</span><span class="typ">: com.mysql.cj.jdbc.Driver（缺省）</span></li></ul><ul class="dgm-kv"><li><span class="fld">connectionTestQuery</span><span class="typ">: "SELECT 1"（未配置时自动设置）</span></li></ul><ul class="dgm-kv"><li><span class="fld">maximumPoolSize</span><span class="typ">: 20（默认，db.pool.config.* 可覆盖）</span></li></ul><ul class="dgm-kv"><li><span class="fld">minimumIdle</span><span class="typ">: 2（默认）</span></li></ul><ul class="dgm-kv"><li><span class="fld">connectionTimeout</span><span class="typ">: 3000ms（默认）</span></li></ul><ul class="dgm-kv"><li><span class="fld">idleTimeout</span><span class="typ">: 600000ms（10min，默认）</span></li></ul><ul class="dgm-kv"><li><span class="fld">validationTimeout</span><span class="typ">: 10000ms（默认）</span></li></ul></div></div></div>

### 6.5.3 源码走读

#### 6.5.3.1 init()——HikariCP 连接池初始化

`ExternalDataSourceServiceImpl.init()`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/ExternalDataSourceServiceImpl.java:87-127`）：

```java
@Override
public void init() {
    queryTimeout = ConvertUtils.toInt(System.getProperty("QUERYTIMEOUT"), 3);
    jt = new JdbcTemplate();
    // Set the maximum number of records to prevent memory expansion
    jt.setMaxRows(50000);
    jt.setQueryTimeout(queryTimeout);
    
    testMasterJT = new JdbcTemplate();
    testMasterJT.setQueryTimeout(queryTimeout);
    
    testMasterWritableJT = new JdbcTemplate();
    testMasterWritableJT.setQueryTimeout(1);
    
    testJtList = new ArrayList<>();
    isHealthList = new ArrayList<>();
    
    tm = new DataSourceTransactionManager();
    tjt = new TransactionTemplate(tm);
    tjt.setTimeout(TRANSACTION_QUERY_TIMEOUT);
    
    dataSourceType = DatasourcePlatformUtil.getDatasourcePlatform(defaultDataSourceType);
    
    if (DatasourceConfiguration.isUseExternalDB()) {
        try {
            reload();   // 构建多数据源连接池列表
        } catch (IOException e) {
            throw new RuntimeException(DB_LOAD_ERROR_MSG, e);
        }
        // 数据源数量超过阈值时启用主库选择任务
        if (this.dataSourceList.size() > DB_MASTER_SELECT_THRESHOLD) {
            PersistenceExecutor.scheduleTask(new SelectMasterTask(), 10, 10, TimeUnit.SECONDS);
        }
        // 数据库健康检查任务（每 10 秒）
        PersistenceExecutor.scheduleTask(new CheckDbHealthTask(), 10, 10, TimeUnit.SECONDS);
    }
}
```

`reload()`（`:130-170`）经 `ExternalDataSourceProperties.build(EnvUtil.getEnvironment(), ...)` 绑定 `db.num`/`db.url.N`/`db.user.N`/`db.password.N` 多数据源配置——为每个数据源创建 `HikariDataSource`（连接池默认值由 `DataSourcePoolProperties` 提供）并做 `ConnectionCheckUtil.checkDataSourceConnection()` fail-fast 校验——随后原子替换 `dataSourceList`/`testJtList`/`isHealthList`、立即执行一轮 `SelectMasterTask` 与 `CheckDbHealthTask`、最后关闭旧连接池。

### 6.5.4 设计模式分析

1. **对象池模式（Object Pool）**：HikariCP 连接池（`HikariDataSource`）管理 MySQL 连接的创建、复用和销毁——`ExternalDataSourceServiceImpl.reload()`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/ExternalDataSourceServiceImpl.java:130-170`）经 `ExternalDataSourceProperties`（绑定 `db.num`/`db.url.N`/`db.user.N`/`db.password.N` 多数据源前缀）为每个数据源创建连接池——池参数由 `DataSourcePoolProperties` 提供默认值：`maxPoolSize=20`、`minimumIdle=2`、`connectionTimeout=3s`、`idleTimeout=10min`、`validationTimeout=10s`（可经 `db.pool.config.*` 覆盖）。未显式配置校验 SQL 时自动设置 `connectionTestQuery="SELECT 1"`——HikariCP 借此在连接借出时进行有效性校验——无效连接自动剔除并创建新连接。

2. **工厂模式（Factory）**：`HikariDataSource` 作为连接工厂——通过 `getConnection()` 从对象池获取可用连接。`ExternalDataSourceServiceImpl` 将 `HikariDataSource` 列表包装为统一的 `DataSourceService` 契约——`DynamicDataSource`（`persistence/.../datasource/DynamicDataSource.java:26-64`）按 `isEmbeddedStorage()` 静态标志在本地 Derby 与外部数据源之间二选一（不支持运行时读写分离路由）。

3. **门面模式（Facade）**：`ExternalDataSourceServiceImpl` 封装了 HikariCP 连接池的初始化、配置验证、健康检查、重载、关闭等全生命周期管理——向 `persistence/` 模块的其他类（如 `BaseDatabaseOperate`/`ExternalStoragePaginationHelperImpl`）提供统一的 `DataSource`/`JdbcTemplate`/`TransactionTemplate` 访问门面。

### 6.5.5 Trade-off 分析

**表 6.5：HikariCP vs DriverManager vs DBCP2 trade-off**

| 权衡维度 | HikariCP 连接池（Nacos 选择） | 单连接 DriverManager | DBCP2 连接池 |
|---------|-----------------------------|--------------------|--------------|
| **并发能力** | ✅ 多连接并发读写——`maximumPoolSize=20` 可并行处理 20 个 SQL 操作 | ❌ 单连接串行——所有 SQL 排队等待唯一连接 | ✅ 多连接并发——连接池复用——DBCP2 性能约 1.5x 耗时 vs HikariCP |
| **连接复用** | ✅ 连接池复用——避免 TCP 三次握手 + MySQL 认证开销（~10ms/次） | ❌ 每次新建连接——TCP 三次握手 + MySQL 认证开销 | ✅ 连接池复用 |
| **连接超时** | `connectionTimeout=3,000ms`（默认）——超时抛 `CannotGetJdbcConnectionException`，`db.pool.config.connectionTimeout` 可覆盖 | 无超时控制——可能无限等待 TCP 连接 | `maxWaitMillis` 默认无限制 |
| **空闲回收** | `idleTimeout=600000ms`（10 分钟）自动回收连接 + `minimumIdle=2` 保持最小空闲连接数（默认） | 无自动回收——需手动关闭连接 | `timeBetweenEvictionRunsMillis` + `minEvictableIdleTimeMillis` |
| **性能基准** | ✅ 1,000,000 次 `getConnection()`/`close()` 仅 ~30ms（HikariCP 基准测试） | ❌ 1,000,000 次 `DriverManager.getConnection()` 需 ~10,000ms | ⚠️ 性能略低于 HikariCP（约 1.5x 耗时） |
| **监控集成** | ✅ Micrometer `DatasourceMetrics.getDbException()` 暴露数据库异常计数器（`nacos_exception{module=config,name=db}`） | ❌ 无监控集成 | ⚠️ 需手动集成 JMX MBean |

Nacos 2.5.3 选择 HikariCP 而非 DBCP2 的核心原因：HikariCP 是 Spring Boot 2.x 默认连接池——零额外依赖，且性能基准优于 DBCP2（HikariCP 基准测试 ~30ms/百万次 `getConnection()`/`close()` vs DBCP2 ~45ms）。`persistence/` 模块通过 `DataSourcePoolProperties` 绑定 `db.pool.config` 配置前缀（`DataSourcePoolProperties.java:64`）——运维人员可通过 `application.properties` 覆盖默认值（如 `db.pool.config.maximumPoolSize=50`）。代价是 HikariCP 的连接验证依赖于 `connectionTestQuery="SELECT 1"`（用户未配置时由 `ExternalDataSourceProperties` 自动设置）——每次校验执行 `SELECT 1` 增加 MySQL 服务器额外负载——但 `SELECT 1` 是 MySQL 最轻量级查询（无需访问任何表），对 MySQL 服务器负载影响可忽略。

### 6.5.6 小结

`ExternalDataSourceServiceImpl.init()`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/ExternalDataSourceServiceImpl.java:87-127`）构建多个预设超时的 `JdbcTemplate` 并在 `isUseExternalDB()` 时触发 `reload()`——`ExternalDataSourceProperties`（`persistence/.../ExternalDataSourceProperties.java:75-98`）绑定 `db.num`/`db.url.N`/`db.user.N`/`db.password.N` 多数据源配置——连接池默认值由 `DataSourcePoolProperties` 提供（`maxPoolSize=20`/`minimumIdle=2`/`connectionTimeout=3s`/`idleTimeout=10min`，可经 `db.pool.config.*` 覆盖）。`getHealth()`（`:215-229`）基于 `CheckDbHealthTask` 维护的 `isHealthList` 返回 `UP`/`WARN:ip`/`DOWN:ip`。`DatasourceMetrics`（`persistence/.../monitor/DatasourceMetrics.java:27-34`）仅提供数据库异常计数器 `getDbException()`。适用于生产环境大集群（>10 节点）——HikariCP 连接池支持高并发读写、连接复用、定时健康检查。嵌入式 Derby 实现参见 6.4 节。
### 6.6.1 设计背景

`PaginationHelper<E>` 是接口（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/PaginationHelper.java:29-50`）——而非抽象基类——仅定义分页查询契约：`fetchPage()` 两个重载（`sqlCountRows`+`sqlFetchRows`+`args`+页码页大小+`RowMapper`，其中一个支持 `lastMaxId`）、`fetchPageLimit()` 四个重载（其中一个直接接收 `nacos-datasource-plugin` 的 `MapperResult` 对——计数 SQL 与取数 SQL 分别由 Mapper 生成）、以及 `updateLimit(sql, args)` 带页大小上限的更新。接口没有 `findAll()`/`findOne()`/`count()`/`insert()`/`update()`/`delete()` 等通用 CRUD 方法，也没有 `generateLimitSql()` 这类方言钩子——方言差异由 Mapper 层吸收。`EmbeddedPaginationHelperImpl`（`persistence/repository/embedded/EmbeddedPaginationHelperImpl.java:34-150`）实现该接口——它不拼接任何分页 SQL——计数与取数 SQL 均为入参透传，执行委托给构造注入的 `DatabaseOperate`（`:38-40`）；`updateLimit()` 则把 SQL 放入 `EmbeddedStorageContextHolder` 后经 `databaseOperate.update()` 一次性提交。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过 `ThreadLocal<ArrayList<ModifyRequest>>`（`SQL_CONTEXT`）与 `ThreadLocal<Map<String, String>>`（`EXTEND_INFO_CONTEXT`）按线程累积待执行 SQL 与扩展信息。

### 6.6.2 核心类关系图

图 6-6 展示了 `PaginationHelper<E>` 接口与 `EmbeddedPaginationHelperImpl` 的分页机制：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">PaginationHelper&lt;E&gt; (interface)</span><span class="s">+ fetchPage(sqlCountRows, sqlFetchRows, args, pageNo, pageSize, rowMapper)</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">→ Page&lt;E&gt;（fetchPage × 2，其一支持 lastMaxId）</div><div class="dgm-note" style="border:none;background:none;padding:0;">+ fetchPageLimit(...) → Page&lt;E&gt;（× 4，其一接收 MapperResult 对）</div><div class="dgm-note" style="border:none;background:none;padding:0;">+ updateLimit(sql, args) → void</div></div></div><div class="dgm-note">△                              △</div><div class="dgm-box"><div class="dgm-box-h"><span class="t">EmbeddedPagination</span><span class="s">HelperImpl&lt;E&gt;</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">构造参数: DatabaseOperate</div><div class="dgm-note" style="border:none;background:none;padding:0;">doFetchPage():</div><div class="dgm-note" style="border:none;background:none;padding:0;">queryOne(sqlCountRows) 计总数</div><div class="dgm-note" style="border:none;background:none;padding:0;">queryMany(sqlFetchRows) 取当页</div><div class="dgm-note" style="border:none;background:none;padding:0;">（SQL 均为入参透传，不拼接分页子句）</div><div class="dgm-note" style="border:none;background:none;padding:0;">updateLimit():</div><div class="dgm-note" style="border:none;background:none;padding:0;">addSqlContext → databaseOperate.update</div></div></div></div>

### 6.6.3 源码走读

#### 6.6.3.1 PaginationHelper<E> 接口与 Derby 实现

`EmbeddedPaginationHelperImpl`（`persistence/.../repository/embedded/EmbeddedPaginationHelperImpl.java:34-150`——嵌入式 Derby 实现）：

```java
public class EmbeddedPaginationHelperImpl<E> implements PaginationHelper<E> {
    
    private final DatabaseOperate databaseOperate;
    
    public EmbeddedPaginationHelperImpl(DatabaseOperate databaseOperate) {
        this.databaseOperate = databaseOperate;
    }
    
    private Page<E> doFetchPage(final String sqlCountRows, final Object[] countAgrs, final String sqlFetchRows,
            final Object[] fetchArgs, final int pageNo, final int pageSize, final RowMapper rowMapper) {
        checkPageInfo(pageNo, pageSize);
        // 查询当前记录总数——SQL 为入参透传
        Integer rowCountInt = (null != countAgrs)
                ? databaseOperate.queryOne(sqlCountRows, countAgrs, Integer.class)
                : databaseOperate.queryOne(sqlCountRows, Integer.class);
        if (rowCountInt == null) {
            throw new IllegalArgumentException("fetchPageLimit error");
        }
        // 计算总页数
        int pageCount = rowCountInt / pageSize;
        if (rowCountInt > pageSize * pageCount) {
            pageCount++;
        }
        final Page<E> page = new Page<>();
        page.setPageNumber(pageNo);
        page.setPagesAvailable(pageCount);
        page.setTotalCount(rowCountInt);
        if (pageNo > pageCount) {
            return page;
        }
        // 取当前页数据——SQL 由 nacos-datasource-plugin 的 Mapper 生成后透传
        List<E> result = databaseOperate.queryMany(sqlFetchRows, fetchArgs, rowMapper);
        for (E item : result) {
            page.getPageItems().add(item);
        }
        return page;
    }
    
    @Override
    public void updateLimit(final String sql, final Object[] args) {
        EmbeddedStorageContextHolder.addSqlContext(sql, args);
        try {
            databaseOperate.update(EmbeddedStorageContextHolder.getCurrentSqlContext());
        } finally {
            EmbeddedStorageContextHolder.cleanAllContext();
        }
    }
}
```

#### 6.6.3.2 EmbeddedStorageContextHolder

`EmbeddedStorageContextHolder` 通过两个 `ThreadLocal`——`SQL_CONTEXT`（`ArrayList<ModifyRequest>`）与 `EXTEND_INFO_CONTEXT`（`Map<String, String>`）——按线程累积待执行 SQL 与扩展信息，保证多线程环境下各线程的 SQL 攒批互不干扰。

### 6.6.4 设计模式分析

1. **接口抽象模式（Interface Abstraction）**：`PaginationHelper<E>` 是接口（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/PaginationHelper.java:29-50`）——定义 `fetchPage()`×2、`fetchPageLimit()`×4、`updateLimit()` 分页契约。它不做模板方法式的骨架固化——也没有 `generateLimitSql()` 方言钩子——分页流程（先计总数、再取当页）由各实现类自行组织（`EmbeddedPaginationHelperImpl.doFetchPage()`，`EmbeddedPaginationHelperImpl.java:114-149`）。

2. **策略模式（Strategy）**：`EmbeddedPaginationHelperImpl`（嵌入式，委托 `DatabaseOperate`）和 `ExternalStoragePaginationHelperImpl`（外部 MySQL，委托 `JdbcTemplate`）两种分页策略——由持有方（各 `DatabaseOperate` 实现/仓储类）按数据源类型手动 `new` 对应实现（`EmbeddedPaginationHelperImpl` 构造参数为 `DatabaseOperate`，`EmbeddedPaginationHelperImpl.java:38-40`）——并非 Spring Bean 自动注入。策略模式使切换数据库无需修改分页调用代码。

3. **上下文持有者模式（Context Holder）**：`EmbeddedStorageContextHolder`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过两个 `ThreadLocal` 持有嵌入式存储的 SQL 攒批上下文——`SQL_CONTEXT`（`ArrayList<ModifyRequest>`）与 `EXTEND_INFO_CONTEXT`（`Map<String, String>`）。每个 HTTP 请求线程独立累积自己的待执行 SQL——`blockUpdate()` 提交时一次性取出并清理——实现线程级的写请求聚合。

### 6.6.5 Trade-off 分析

**表 6.6：Derby OFFSET FETCH vs MySQL LIMIT trade-off**

| 权衡维度 | Derby `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | MySQL `LIMIT ? OFFSET ?` | 应用程序内存分页 |
|---------|--------------------------|----------------------------|---------------|
| **SQL 标准** | ✅ SQL:2008 标准——所有 SQL:2008 兼容数据库支持 | ⚠️ MySQL 方言——仅 MySQL/MariaDB 支持 | ✅ 零 SQL 依赖 |
| **性能** | ⚠️ 大偏移量性能下降——Derby 需扫描跳过 OFFSET 行 | 同左——InnoDB 需扫描跳过 OFFSET 行 | ❌ 全量加载到 JVM 内存——O(n) 内存消耗 |
| **适用场景** | 嵌入式 Derby（测试/单机≤50,000 行） | 外部 MySQL（生产集群>50,000 行） | 小数据集（<10,000 行） |
| **连接管理** | ✅ 嵌入式——零网络开销、零连接池配置 | ⚠️ HikariCP 连接池管理——需配置 poolSize/minIdle/maxLifetime | ✅ 零数据库连接 |
| **持久化** | ❌ 嵌入式 Derby 数据存储在本地文件——节点重启后数据仍存在（非内存数据库） | ✅ MySQL 数据持久化到磁盘——支持主从复制 | ❌ 纯内存——重启后数据丢失 |

Nacos 2.5.3 选择嵌入式 Derby 用于单机和测试环境的核心原因：零外部依赖——无需部署外部 MySQL 数据库，降低单机部署的运维复杂度。`LocalDataSourceServiceImpl.init()`（`persistence/src/main/java/com/alibaba/nacos/persistence/datasource/LocalDataSourceServiceImpl.java:78-89`）自动创建嵌入式 Derby 数据库并经 `reload()` 执行建表脚本——无需用户手动执行 SQL 建表脚本。代价是嵌入式 Derby 在并发读写场景下性能不如 MySQL——但 Nacos 单机模式通常仅服务于小规模配置管理（<100 个客户端），嵌入式 Derby 的性能完全满足需求。对于生产集群模式，`DatasourceConfiguration` 置位的外部库标志使 `DynamicDataSource` 自动选择 `ExternalDataSourceServiceImpl`——使用 HikariCP 连接池连接外部 MySQL——支持高并发读写。

### 6.6.6 小结

`PaginationHelper<E>` 是接口（`persistence/repository/PaginationHelper.java:29-50`）——仅定义 `fetchPage()`×2、`fetchPageLimit()`×4 与 `updateLimit()` 分页契约。`EmbeddedPaginationHelperImpl`（`persistence/repository/embedded/EmbeddedPaginationHelperImpl.java:34-150`）实现该接口——不拼接分页 SQL——方言 SQL 由 `nacos-datasource-plugin` 的 Mapper 生成后经构造注入的 `DatabaseOperate` 透传执行。`EmbeddedStorageContextHolder`（`persistence/repository/embedded/EmbeddedStorageContextHolder.java:31-119`）通过 `ThreadLocal<ArrayList<ModifyRequest>>` 与 `ThreadLocal<Map<String, String>>` 按线程累积待执行 SQL 与扩展信息。外部 MySQL 分页实现参见 6.8 节。


### 6.7.1 设计背景

`DatabaseOperate` 接口（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/operate/DatabaseOperate.java:35-154`）定义嵌入式存储 SQL 操作的统一抽象——三个 `queryOne()` 重载（`sql+Class`/`sql+args+Class`/`sql+args+RowMapper`）、三个 `queryMany()` 重载（返回 `List<R>` 或 `List<Map<String, Object>>`）、`update(List<ModifyRequest>, BiConsumer<Boolean, Throwable>)` 批量写（成功/失败经回调通知）、`dataImport(File)` 外部数据导入（返回 `CompletableFuture<RestResult<String>>`）以及两个 default 方法 `update(List<ModifyRequest>)` 与 `blockUpdate()`——后者取出当前线程 `EmbeddedStorageContextHolder` 中的 SQL 列表一次性提交并自动清理。不存在 `doOperate(ModifyRequest)`/`CountRequest`/`OneRequest` 这样的方法与请求类型。`BaseDatabaseOperate`（`BaseDatabaseOperate.java:46-275`）是 `extends DatabaseOperate` 的接口——以 default 方法提供 `queryOne()`×3（`:59-121`）、`queryMany()`×3（`:133-190`）、`update()`×2（`:200-259`）与 `doDataImport()`（`:268-273`）的通用 `JdbcTemplate` 实现。`StandaloneDatabaseOperateImpl`（`persistence/repository/embedded/operate/StandaloneDatabaseOperateImpl.java:53-55`）以 `@Conditional(ConditionStandaloneEmbedStorage.class)` + `@Component` 注册、`implements BaseDatabaseOperate`——`@PostConstruct` 经 `DynamicDataSource.getInstance().getDataSource()` 获取 `JdbcTemplate`/`TransactionTemplate`。`ModifyRequest`（`persistence/repository/embedded/sql/ModifyRequest.java:28-83`）是纯 POJO——字段仅 `executeNo`/`sql`/`rollBackOnUpdateFail`/`args`——即"sql + 参数数组 + 失败回滚标志"的可序列化写请求，无 Builder；`SelectRequest`（`SelectRequest.java:27-128`）字段为 `queryType(byte)`/`sql`/`args`/`className`——`SelectRequestBuilder` 仅提供这四项的链式设置。`SqlTypeLimiter`（`SqlTypeLimiter.java:35-146`）是 SQL 类型白名单安全限制器——只放行 `INSERT`/`UPDATE`/`DELETE`/`SELECT` 与 `CREATE SCHEMA|TABLE|INDEX`/`ALTER TABLE`——开关 `nacos.persistence.sql.derby.limit.enabled` 默认 true——与分页方言适配无关。

### 6.7.2 核心类关系图

图 6-7 展示了 `DatabaseOperate` 接口体系与 `ModifyRequest`/`SelectRequest` 的关系：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">&lt;&lt;interface&gt;&gt; DatabaseOperate</span><span class="s">queryOne(sql, cls) / queryOne(sql, args, cls) / queryOne(sql, args, mapper)</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">queryMany(sql, args, mapper) / queryMany(sql, args, cls) / queryMany(sql, args)</div><div class="dgm-note" style="border:none;background:none;padding:0;">update(List&lt;ModifyRequest&gt;, BiConsumer) / dataImport(File)</div><div class="dgm-note" style="border:none;background:none;padding:0;">default: update(List) / blockUpdate() — 取当前线程 SQL 上下文一次性提交</div></div></div><div class="dgm-note">△  extends（default 方法提供 JdbcTemplate 通用实现）</div><div class="dgm-box"><div class="dgm-box-h"><span class="t">&lt;&lt;interface&gt;&gt; BaseDatabaseOperate</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">default queryOne × 3 / queryMany × 3 / update × 2 / doDataImport</div></div></div><div class="dgm-note">△  implements</div><div class="dgm-box"><div class="dgm-box-h"><span class="t">StandaloneDatabaseOperateImpl</span><span class="s">@Conditional(ConditionStandaloneEmbedStorage) + @Component</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">jdbcTemplate</span><span class="typ">: JdbcTemplate（@PostConstruct 经 DynamicDataSource 获取）</span></li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">update(List&lt;ModifyRequest&gt;): 事务内逐条 update，失败按 rollBackOnUpdateFail 回滚</div><div class="dgm-note" style="border:none;background:none;padding:0;">queryOne/queryMany: 委托 BaseDatabaseOperate default 方法</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">ModifyRequest (纯 POJO, Serializable)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">executeNo</span><span class="typ">: int（SQL 攒批序号）</span></li></ul><ul class="dgm-kv"><li><span class="fld">sql</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">args</span><span class="typ">: Object[]</span></li></ul><ul class="dgm-kv"><li><span class="fld">rollBackOnUpdateFail</span><span class="typ">: boolean</span></li></ul></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">SelectRequest (Serializable)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">queryType</span><span class="typ">: byte（对应 JdbcTemplate 方法）</span></li></ul><ul class="dgm-kv"><li><span class="fld">sql</span><span class="typ">: String</span></li></ul><ul class="dgm-kv"><li><span class="fld">args</span><span class="typ">: Object[]</span></li></ul><ul class="dgm-kv"><li><span class="fld">className</span><span class="typ">: String</span></li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">SelectRequestBuilder: queryType/sql/args/className 四项链式设置</div></div></div></div>

### 6.7.3 源码走读

#### 6.7.3.1 DatabaseOperate 接口

`DatabaseOperate`（`persistence/.../repository/embedded/operate/DatabaseOperate.java:35-154`）：

```java
public interface DatabaseOperate {
    
    <R> R queryOne(String sql, Class<R> cls);
    <R> R queryOne(String sql, Object[] args, Class<R> cls);
    <R> R queryOne(String sql, Object[] args, RowMapper<R> mapper);
    
    <R> List<R> queryMany(String sql, Object[] args, RowMapper<R> mapper);
    <R> List<R> queryMany(String sql, Object[] args, Class<R> rClass);
    List<Map<String, Object>> queryMany(String sql, Object[] args);
    
    Boolean update(List<ModifyRequest> modifyRequests, BiConsumer<Boolean, Throwable> consumer);
    
    default Boolean update(List<ModifyRequest> modifyRequests) {
        return update(modifyRequests, null);
    }
    
    CompletableFuture<RestResult<String>> dataImport(File file);
    
    default Boolean blockUpdate() {
        return blockUpdate(null);
    }
    
    default Boolean blockUpdate(BiConsumer<Boolean, Throwable> consumer) {
        try {
            return update(EmbeddedStorageContextHolder.getCurrentSqlContext(), consumer);
        } finally {
            EmbeddedStorageContextHolder.cleanAllContext();
        }
    }
}
```

#### 6.7.3.2 StandaloneDatabaseOperateImpl

`StandaloneDatabaseOperateImpl`（`persistence/.../repository/embedded/operate/StandaloneDatabaseOperateImpl.java:53-100`）：

```java
@Conditional(ConditionStandaloneEmbedStorage.class)
@Component
public class StandaloneDatabaseOperateImpl implements BaseDatabaseOperate {
    
    private final SqlLimiter sqlLimiter;
    private JdbcTemplate jdbcTemplate;
    private TransactionTemplate transactionTemplate;
    
    public StandaloneDatabaseOperateImpl() {
        this.sqlLimiter = new SqlTypeLimiter();
    }
    
    @PostConstruct
    protected void init() {
        // 经 DynamicDataSource 单例获取当前数据源的 JdbcTemplate/TransactionTemplate
        DataSourceService dataSourceService = DynamicDataSource.getInstance().getDataSource();
        jdbcTemplate = dataSourceService.getJdbcTemplate();
        transactionTemplate = dataSourceService.getTransactionTemplate();
        LOGGER.info("use StandaloneDatabaseOperateImpl");
    }
    
    @Override
    public <R> R queryOne(String sql, Class<R> cls) {
        return queryOne(jdbcTemplate, sql, cls);   // 委托 BaseDatabaseOperate default 方法
    }
    
    @Override
    public CompletableFuture<RestResult<String>> dataImport(File file) {
        return CompletableFuture.supplyAsync(() -> { /* 解析文件并批量写入 Derby */ });
    }
}
```

`update(List<ModifyRequest>)` 的核心逻辑在 `BaseDatabaseOperate` 的 default 实现中：以 `transactionTemplate.execute()` 开启事务——逐条 `jdbcTemplate.update()` 执行 `ModifyRequest`——执行前经 `sqlLimiter` 做类型白名单校验——某条失败且其 `rollBackOnUpdateFail=true` 时整体回滚并回调通知。

### 6.7.4 设计模式分析

1. **命令模式（Command）**：`ModifyRequest`（`persistence/repository/embedded/sql/ModifyRequest.java:28-83`）封装一条可序列化的写命令——`sql` + `args` 参数数组 + `rollBackOnUpdateFail` 失败回滚标志 + `executeNo` 攒批序号。`EmbeddedStorageContextHolder` 按 `executeNo` 顺序累积命令——`BaseDatabaseOperate.update()`（`persistence/repository/embedded/operate/BaseDatabaseOperate.java:200-259`）作为命令执行器——在事务内将 `ModifyRequest` 逐条转换为 `JdbcTemplate.update()` 调用。命令模式将 SQL 请求对象（Command）与执行器（Invoker）解耦——新增 SQL 操作只需构造新的 `ModifyRequest`，无需修改执行分发逻辑。

2. **骨架复用模式（Default Method Reuse）**：`BaseDatabaseOperate`（`BaseDatabaseOperate.java:46-275`）以 `extends DatabaseOperate` 的接口 + default 方法形式提供 `queryOne()`×3/`queryMany()`×3/`update()`×2 的通用 `JdbcTemplate` 实现——`StandaloneDatabaseOperateImpl` 等实现类各自只补充差异逻辑——公共 CRUD 骨架零重复。

3. **模板方法模式（Template Method）**：`DatabaseOperate` 接口定义 `queryOne()`/`queryMany()`/`update()`/`dataImport()`/`blockUpdate()` 统一 SQL 操作契约——`blockUpdate()` 的 default 实现（取出线程 SQL 上下文→提交→finally 清理）固定了"攒批-提交-清理"骨架流程——具体执行由 `update()` 的实现方完成。

### 6.7.5 Trade-off 分析

**表 6.7：SQL 请求模型 vs 字符串拼接 vs MyBatis trade-off**

| 权衡维度 | SQL 请求模型 `ModifyRequest`/`SelectRequest`（Nacos 选择） | 字符串拼接 SQL | MyBatis XML Mapper |
|---------|------------------------------|----------------|-------------------|
| **类型安全** | ✅ `sql + args` 参数数组结构化承载——SQL 与参数分离 | ❌ 运行时字符串拼接——类型错误运行时才暴露 | ✅ XML Mapper 编译期生成代理 |
| **SQL 注入防护** | ✅ `PreparedStatement.setObject()` 参数化绑定——从根本上杜绝 SQL 注入 | ❌ 需手动转义单引号/分号等特殊字符——易遗漏 | ✅ `#{}` 预编译占位符 |
| **可维护性** | ✅ 请求对象可序列化——攒批、跨进程传递（分布式场景）友好 | ❌ 多行字符串拼接——SQL 与 Java 代码混杂 | ⚠️ XML Mapper 分散在多个 XML 文件中——跨文件追踪 SQL 逻辑困难 |
| **安全边界** | ✅ `SqlTypeLimiter` SQL 类型白名单——拦截非白名单 SQL | ✅ 无任何适配——直接写特定数据库 SQL | ⚠️ 需配置 Hibernate Dialect 或 MyBatis DatabaseIdProvider |
| **学习成本** | ⚠️ 需了解 `ModifyRequest`/`SelectRequest` 请求对象语义 | ✅ 通用 SQL 知识——无额外 API 学习 | ❌ 需学习 MyBatis XML 语法——`<select>/<insert>/<resultMap>` |

Nacos 2.5.3 选择 SQL 请求对象模型而非 MyBatis 的核心原因：`persistence/` 模块的写操作需要"攒批-事务提交-失败回滚"语义（`EmbeddedStorageContextHolder` 攒批 + `ModifyRequest.rollBackOnUpdateFail`）——且分布式场景下请求对象需可序列化传输。MyBatis 的 `DatabaseIdProvider` 虽可配置多数据库 SQL——但需为每个 SQL 语句维护 XML Mapper，与 Nacos 基于 `nacos-datasource-plugin` Mapper 插件生成 SQL 的路线不匹配。`SqlTypeLimiter` 将 SQL 类型白名单校验集中在 SQL 执行入口——任何绕过校验的 SQL 都会被 `SQLException` 拒绝。代价是需了解请求对象模型——但字段极少（4 个），学习曲线平缓。

### 6.7.6 小结

`DatabaseOperate` 接口定义 `queryOne()`×3/`queryMany()`×3/`update()`/`dataImport()`/`blockUpdate()` 统一 SQL 操作契约——`BaseDatabaseOperate`（接口 extends）以 default 方法提供 `JdbcTemplate` 通用实现。`StandaloneDatabaseOperateImpl`（`persistence/repository/embedded/operate/StandaloneDatabaseOperateImpl.java:53-55`）以 `@Conditional(ConditionStandaloneEmbedStorage.class)` + `@Component` 注册——`@PostConstruct` 经 `DynamicDataSource` 获取 `JdbcTemplate`/`TransactionTemplate`。`ModifyRequest`/`SelectRequest`（`persistence/repository/embedded/sql/ModifyRequest.java:28-83` / `SelectRequest.java:27-128`）是 SQL + 参数数组的请求对象——`PreparedStatement.setObject()` 参数化绑定从根本上杜绝 SQL 注入。`SqlTypeLimiter`（`SqlTypeLimiter.java:35-146`）是 SQL 类型白名单安全限制器——只放行 DML 与部分 DDL——与分页方言适配无关。


### 6.8.1 设计背景

`ExternalStoragePaginationHelperImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/extrnal/ExternalStoragePaginationHelperImpl.java:34-147`）是 `PaginationHelper<E>` 接口的外部 MySQL 分页实现——与嵌入式实现的差异在执行通道而非 SQL 生成：它构造注入 `JdbcTemplate`（`:38-40`）并直接执行透传的计数/取数 SQL——SQL 本身由 `nacos-datasource-plugin` 的 Mapper 生成（MySQL 方言含 `LIMIT` 分页子句），实现类内部不拼接分页子句。当 `DatasourceConfiguration.isUseExternalDB()` 为 true 时由持有方手动 `new` 并注入外部数据源的 `JdbcTemplate`——与 `ExternalDataSourceServiceImpl`（HikariCP 连接池）配合使用，适用于生产环境大集群（>10 节点）的高并发读写场景。性能方面：MySQL InnoDB 在大偏移量场景下（如 `LIMIT 1000000, 10`）需扫描跳过 1,000,010 行——建议使用游标分页（`WHERE id > last_id LIMIT 10`）或 ElasticSearch 搜索引擎代替深分页。

### 6.8.2 核心类关系图

图 6-8 展示了 `ExternalStoragePaginationHelperImpl` 基于 `JdbcTemplate` 透传执行的分页实现：

<div class="dgm"><div class="dgm-cap"><span class="no">6.8.2</span><span class="tt">ExternalStoragePaginationHelperImpl 分页实现</span></div><div class="dgm-panel"><div class="dgm-panel-head"><span class="t">ExternalStoragePaginationHelperImpl&lt;E&gt;</span><span class="s">implements PaginationHelper&lt;E&gt;（构造注入 JdbcTemplate）</span></div><div class="dgm-panel-body"><div class="dgm-box"><div class="dgm-box-h"><span class="t">doFetchPage(sqlCountRows, sqlFetchRows, args, pageNo, pageSize, rowMapper)</span></div><div class="dgm-box-b"><div class="dgm-kv"><li>queryForObject(sqlCountRows, args, Integer.class) 计总数</li><li>→ jdbcTemplate.query(sqlFetchRows, args, rowMapper) 取当页</li><li>（SQL 由 Mapper 生成后透传，实现类不拼接分页子句）</li></div></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">updateLimit(sql, args): void</span></div><div class="dgm-box-b"><div class="dgm-kv"><li>→ jdbcTemplate.update(sql, args)</li></div></div></div></div></div></div>

### 6.8.3 源码走读

`ExternalStoragePaginationHelperImpl.doFetchPage()`——`JdbcTemplate` 透传执行：

```java
private Page<E> doFetchPage(final String sqlCountRows, final Object[] countAgrs, final String sqlFetchRows,
        final Object[] fetchArgs, final int pageNo, final int pageSize, final RowMapper rowMapper) {
    checkPageInfo(pageNo, pageSize);
    final Page<E> page = new Page<>();
    // line 115-120: 计数 SQL 为入参透传（MySQL 方言由 Mapper 生成）
    Integer rowCountInt = null;
    if (null != countAgrs) {
        rowCountInt = jdbcTemplate.queryForObject(sqlCountRows, countAgrs, Integer.class);
    } else {
        rowCountInt = jdbcTemplate.queryForObject(sqlCountRows, Integer.class);
    }
    // 计算总页数后取当页——取数 SQL 同样透传
    ...
    List<E> result = jdbcTemplate.query(sqlFetchRows, fetchArgs, rowMapper);
    for (E item : result) {
        page.getPageItems().add(item);
    }
    return page;
}
```

### 6.8.4 设计模式分析

1. **策略模式（Strategy）**：`EmbeddedPaginationHelperImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/EmbeddedPaginationHelperImpl.java:34-150`，委托 `DatabaseOperate`）与 `ExternalStoragePaginationHelperImpl`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/extrnal/ExternalStoragePaginationHelperImpl.java:34-147`，委托 `JdbcTemplate`）两种分页策略——实现 `PaginationHelper<E>` 接口的 `fetchPage()`/`fetchPageLimit()` 契约，执行通道随存储模式切换。

2. **接口抽象模式（Interface Abstraction）**：`PaginationHelper<E>` 是接口（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/PaginationHelper.java:29-50`）——仅定义 `fetchPage()`×2、`fetchPageLimit()`×4、`updateLimit()` 契约——没有 `findAll()`/`count()`/`generateLimitSql()` 等成员——分页流程与方言子句均由实现类或 Mapper 层处理，接口保持最小面。

3. **适配器模式（Adapter）**：`SqlTypeLimiter`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/sql/limiter/SqlTypeLimiter.java:35-146`）并非分页方言适配器——而是 SQL 类型白名单限制器（仅放行 DML 与部分 DDL，开关 `nacos.persistence.sql.derby.limit.enabled` 默认 true）——在 SQL 执行入口处拦截非白名单语句。

### 6.8.5 Trade-off 分析

**表 6.8：MySQL LIMIT vs Derby OFFSET FETCH trade-off**

| 权衡维度 | MySQL `LIMIT ? OFFSET ?` | Derby `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` | 应用程序内存分页 |
|---------|--------------------------|--------------------------------------------------|---------------|
| **SQL 简洁性** | ✅ `LIMIT ? OFFSET ?`——8 个字符 | ⚠️ `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`——45 个字符 | ✅ 零 SQL 复杂度——纯 Java 内存操作 |
| **数据库支持** | MySQL/MariaDB/PostgreSQL/H2 | Derby/Apache Derby/HSQLDB | 所有数据库——与数据库无关 |
| **性能** | ⚠️ 大偏移量性能下降——InnoDB 需扫描跳过 OFFSET 行（`LIMIT 1000000, 10` 需扫描 1,000,010 行） | 同左——Derby 同需扫描跳过 OFFSET 行 | ❌ 全量数据加载到应用程序内存——O(n) 内存消耗（n=总行数） |
| **内存开销** | ✅ 仅返回 `pageSize` 行数据——O(pageSize) 内存 | ✅ 仅返回 `pageSize` 行数据 | ❌ 加载全部行到 `List<T>`——O(totalRows) 内存 |
| **适用场景** | ✅ 前端分页查询——每次仅返回 10-50 行 | ✅ 同左 | ❌ 仅适合小数据集（<10,000 行） |

Nacos 2.5.3 选择数据库层分页而非应用程序内存分页的核心原因：`config_info` 表在生产环境中可能包含数十万条历史配置——全量加载到 `List<ConfigInfo>` 会导致 JVM OOM。数据库层分页通过 `LIMIT/OFFSET` 仅返回当前页的 10-50 行数据——内存开销极小。代价是大偏移量性能下降——但 Nacos 控制台的配置管理页面通常只浏览前几页（OFFSET < 1000），大偏移量场景极少出现。对于大偏移量场景（如数据导出），`persistence/` 模块提供流式查询（`JdbcTemplate.query(sql, ResultSetExtractor)`）逐行处理——避免一次性加载全部数据。

### 6.8.6 小结

`EmbeddedPaginationHelperImpl`（`persistence/repository/embedded/EmbeddedPaginationHelperImpl.java:34-150`）与 `ExternalStoragePaginationHelperImpl`（`persistence/repository/extrnal/ExternalStoragePaginationHelperImpl.java:34-147`）均实现 `PaginationHelper<E>` 接口（`:29-50`）——均不拼接分页 SQL——方言分页子句由 `nacos-datasource-plugin` 的 Mapper 生成后透传执行；差异仅在执行通道（`DatabaseOperate` vs `JdbcTemplate`）。`SqlTypeLimiter`（`persistence/repository/embedded/sql/limiter/SqlTypeLimiter.java:35-146`）是 SQL 类型白名单安全限制器——与分页方言适配无关。
### 6.9.1 设计背景

`ModifyRequest`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/sql/ModifyRequest.java:28-83`）和 `SelectRequest`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/sql/SelectRequest.java:27-128`）是 `persistence/` 模块嵌入式存储层的可序列化 SQL 请求对象——而非完整的 SQL 构造 DSL。`ModifyRequest` 是纯 POJO——字段仅 `executeNo`/`sql`/`rollBackOnUpdateFail`/`args`——即"sql + 参数数组 + 失败回滚标志"的写请求；`SelectRequest` 字段为 `queryType(byte)`/`sql`/`args`/`className`——其 `SelectRequestBuilder` 仅提供这四项的链式设置。两者均不包含表名/条件/排序/分页等结构化 SQL 片段——SQL 文本通常由调用方或 `nacos-datasource-plugin` 的 Mapper 生成。所有用户输入通过 `PreparedStatement.setObject(index, value)` 参数化绑定——从根本上杜绝 SQL 注入风险。`QueryType`（`persistence/repository/embedded/sql/QueryType.java:26-58`）是 final 常量类（非枚举）——定义 6 个 `byte` 常量 0-5——逐一对应 `JdbcTemplate` 的查询方法形态（如 `QUERY_ONE_WITH_MAPPER_WITH_ARGS=0` 对应 `queryForObject(String, RowMapper)`、`QUERY_MANY_WITH_LIST_WITH_ARGS=4` 对应 `queryForList(String, Object...)`）——`BaseDatabaseOperate` 按 `queryType` 分发到对应的 `JdbcTemplate` 执行方法。`SqlTypeLimiter`（`persistence/repository/embedded/sql/limiter/SqlTypeLimiter.java:35-146`）是 SQL 类型白名单安全限制器——只放行 `INSERT`/`UPDATE`/`DELETE`/`SELECT` 与 `CREATE SCHEMA|TABLE|INDEX`/`ALTER TABLE`——开关 `nacos.persistence.sql.derby.limit.enabled` 默认 true——与分页方言适配无关。

### 6.9.2 核心类关系图

图 6-9 展示了 `ModifyRequest`/`SelectRequest` SQL 请求对象的层次结构：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">ModifyRequest (纯 POJO, Serializable)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li>sql: String          ← 完整 SQL 语句文本</li><li>args: Object[]       ← 参数绑定数组</li><li>executeNo: int       ← SQL 攒批序号</li><li>rollBackOnUpdateFail: boolean ← 失败回滚标志</li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">无 Builder/tableName/queryType/SqlLimiter 字段</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">SelectRequest (Serializable)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li>queryType: byte      ← 对应 JdbcTemplate 方法形态（0-5）</li><li>sql: String          ← 完整 SQL 语句文本</li><li>args: Object[]       ← 参数绑定数组</li><li>className: String    ← 结果类型类名</li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">SelectRequestBuilder: queryType/sql/args/className 四项链式设置</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">QueryType (final 常量类)</span><span class="s">byte 常量 0-5，对应 JdbcTemplate 方法</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">0 QUERY_ONE_WITH_MAPPER_WITH_ARGS → queryForObject(sql, RowMapper)</div><div class="dgm-note" style="border:none;background:none;padding:0;">1 QUERY_ONE_NO_MAPPER_NO_ARGS     → queryForObject(sql, Class)</div><div class="dgm-note" style="border:none;background:none;padding:0;">2 QUERY_ONE_NO_MAPPER_WITH_ARGS   → queryForObject(sql, args, Class)</div><div class="dgm-note" style="border:none;background:none;padding:0;">3 QUERY_MANY_WITH_MAPPER_WITH_ARGS→ query(sql, args, RowMapper)</div><div class="dgm-note" style="border:none;background:none;padding:0;">4 QUERY_MANY_WITH_LIST_WITH_ARGS  → queryForList(sql, args...)</div><div class="dgm-note" style="border:none;background:none;padding:0;">5 QUERY_MANY_NO_MAPPER_WITH_ARGS  → queryForList(sql, args, Class)</div></div></div></div>

### 6.9.3 源码走读

#### 6.9.3.1 ModifyRequest 写请求

`ModifyRequest`——可序列化的写请求（`ModifyRequest.java:28-83`）：

```java
public class ModifyRequest implements Serializable {
    
    private static final long serialVersionUID = 4548851816596520564L;
    
    private int executeNo;                                    // SQL 攒批序号
    
    private String sql;                                       // 完整 SQL 语句
    
    private boolean rollBackOnUpdateFail = Boolean.FALSE;     // 失败回滚标志
    
    private Object[] args;                                    // 参数绑定数组
    
    public ModifyRequest() {
    }
    
    public ModifyRequest(String sql) {
        this.sql = sql;
    }
    // getter/setter ...
}
```

`ModifyRequest` 没有 Builder、没有表名/条件等 SQL 结构化字段——通常由 `EmbeddedStorageContextHolder.addSqlContext(sql, args)` 在攒批时构造（`executeNo` 取当前列表长度）。

#### 6.9.3.2 SelectRequest 查询请求

`SelectRequest`——可序列化的查询请求（`SelectRequest.java:27-128`）：

```java
public class SelectRequest implements Serializable {
    
    private byte queryType;     // 对应 JdbcTemplate 查询方法形态（QueryType 常量 0-5）
    private String sql;         // 完整 SQL 语句
    private Object[] args;      // 参数绑定数组
    private String className;   // 结果类型类名
    
    public static SelectRequestBuilder builder() {
        return new SelectRequestBuilder();
    }
    
    public static final class SelectRequestBuilder {
        public SelectRequestBuilder queryType(byte queryType) { ... }
        public SelectRequestBuilder sql(String sql) { ... }
        public SelectRequestBuilder args(Object[] args) { ... }
        public SelectRequestBuilder className(String className) { ... }
        public SelectRequest build() { ... }
    }
}
```

`SelectRequestBuilder` 仅提供 `queryType`/`sql`/`args`/`className` 四项——不存在 `select()`/`from()`/`where()`/`orderBy()`/`limit()` 等结构化 SQL 构造方法——SQL 文本由调用方传入。

### 6.9.4 设计模式分析

1. **命令模式（Command）**：`ModifyRequest`（`persistence/src/main/java/com/alibaba/nacos/persistence/repository/embedded/sql/ModifyRequest.java:28-83`）是一条可序列化的写命令——`sql` + `args` + `rollBackOnUpdateFail` + `executeNo`。`EmbeddedStorageContextHolder` 按 `executeNo` 顺序攒批命令——`BaseDatabaseOperate.update()` 在事务内逐条执行。命令对象可序列化的特性使其在分布式场景下也可跨进程传输——这是选择"完整 SQL + 参数数组"而非结构化字段的关键考量。

2. **建造者模式（Builder，仅 SelectRequest）**：`SelectRequest.SelectRequestBuilder`（`SelectRequest.java:77-127`）提供四字段链式设置——`queryType(byte)`→`sql(String)`→`args(Object[])`→`className(String)`→`build()`。`ModifyRequest` 则无 Builder——通过 setter 或 `addSqlContext()` 攒批路径构造。这种不对称源于两者用途差异：查询请求需要明确 `queryType` 以分发 `JdbcTemplate` 方法形态——写请求则在事务内统一走 `update()`。

3. **表驱动分发模式（Constant-driven Dispatch）**：`QueryType` 是 final 常量类（`persistence/repository/embedded/sql/QueryType.java:26-58`）——6 个 `byte` 常量与 `JdbcTemplate` 查询方法形态一一对应——`BaseDatabaseOperate` 按 `SelectRequest.queryType` 分发到对应执行方法（如 `0`→`queryForObject(sql, RowMapper)`）。以常量类而非枚举承载——序列化开销最小（单个 byte）——与请求对象的可序列化设计配套。

### 6.9.5 Trade-off 分析

**表 6.9：SQL 请求对象 vs 字符串拼接 vs ORM trade-off**

| 权衡维度 | SQL 请求对象（Nacos 选择） | 字符串拼接 SQL | ORM 框架（MyBatis/Hibernate） |
|---------|--------------------------|----------------|------------------------------|
| **类型安全** | ✅ `sql + args` 参数数组结构化承载——SQL 与参数分离 | ❌ 运行时字符串拼接——`"WHERE data_id=" + value` 类型错误运行时才暴露 | ✅ XML Mapper 编译期生成代理——类型安全 |
| **SQL 注入防护** | ✅ 参数化查询（`PreparedStatement`）自动防护——`?` 占位符 | ❌ 需手动转义特殊字符——易遗漏 | ✅ 参数化查询自动防护 |
| **可读性** | ✅ 请求对象字段极少（4 个）——语义直观 | ❌ 长字符串难以维护——多行拼接 + 换行符 | ⚠️ XML Mapper 分散在多个 XML 文件中——跨文件追踪 SQL 逻辑困难 |
| **灵活性** | ✅ SQL 文本自由承载——配合 `nacos-datasource-plugin` Mapper 按方言生成 | ✅ 最灵活——可任意拼接任何 SQL 片段 | ⚠️ MyBatis `<if>`/`<choose>` 标签——动态 SQL 能力有限 |
| **学习成本** | ⚠️ 需了解 `queryType` 常量与请求对象语义 | ✅ 通用 SQL 知识——无额外 API 学习 | ❌ 需学习 ORM 框架——MyBatis XML Mapper / Hibernate HQL |

Nacos 2.5.3 选择 SQL 请求对象而非 ORM 框架的核心原因：`persistence/` 模块需要支持嵌入式 Derby 和外部 MySQL 两种数据库——SQL 文本由 `nacos-datasource-plugin` 的 Mapper 插件按数据库方言生成后装入请求对象——方言切换发生在插件层而非请求模型层。ORM 框架通常针对单一数据库优化——跨数据库支持需额外配置（如 Hibernate Dialect）。SQL 请求对象在保持参数化绑定（SQL 注入防护）与可序列化（攒批/跨进程）的前提下，提供了最大的数据库灵活性。`SqlTypeLimiter`（`persistence/repository/embedded/sql/limiter/SqlTypeLimiter.java:35-146`）在执行入口做 SQL 类型白名单校验——提供统一的安全边界而非方言转换。

### 6.9.6 小结

`ModifyRequest`/`SelectRequest`（`persistence/repository/embedded/sql/ModifyRequest.java:28-83` / `SelectRequest.java:27-128`）是可序列化的 SQL 请求对象——`ModifyRequest` 为纯 POJO（`executeNo`/`sql`/`rollBackOnUpdateFail`/`args`），`SelectRequest` 提供 `queryType`/`sql`/`args`/`className` 四字段及其 Builder。`QueryType`（`persistence/repository/embedded/sql/QueryType.java:26-58`）是 final 常量类（byte 常量 0-5）——`BaseDatabaseOperate` 按 `queryType` 分发到对应的 `JdbcTemplate` 执行方法。`SqlTypeLimiter`（`persistence/repository/embedded/sql/limiter/SqlTypeLimiter.java:35-146`）是 SQL 类型白名单安全限制器——在 SQL 执行入口拦截非白名单语句。分页方言 SQL 由 `nacos-datasource-plugin` 的 Mapper 生成后透传——`PaginationHelper` 实现的切换由 `DatasourceConfiguration` 静态标志驱动的存储模式决定——无需修改任何上层 SQL 构造代码。


### 6.10.1 设计背景

`persistence/` 模块的事件体系是**进程内**通知机制——并不承担跨节点快照同步。三个事件均继承 `SlowEvent`（`com.alibaba.nacos.common.notify.SlowEvent`）并经 `NotifyCenter`（单 JVM 事件总线）发布：`DerbyImportEvent`（`persistence/src/main/java/com/alibaba/nacos/persistence/model/event/DerbyImportEvent.java:26-39`——字段仅 `boolean finished`，通知本地 Derby 导入流程的完成状态）、`DerbyLoadEvent`（同目录，通知本地 Derby 加载完成）、`RaftDbErrorEvent`（`RaftDbErrorEvent.java:26-42`——字段仅 `Throwable ex`，数据库操作出现异常时发布，订阅者据此终止服务进程）。跨节点的 CP 快照同步由 JRaft 承担——`NacosStateMachine`（`core/src/main/java/com/alibaba/nacos/core/distributed/raft/NacosStateMachine.java:156,169`）实现 JRaft 的 `onSnapshotSave()`/`onSnapshotLoad()`——经 `JSnapshotOperation`（`JSnapshotOperation.java:41,49`）把各 `NacosStateMachine` 注册的快照处理器（含本地 Derby/磁盘数据）写入或读取 JRaft 快照目录——快照文件随 Raft 日志复制协议在集群间传输与安装。事件体系与 JRaft 快照是两个正交机制：事件只做进程内状态广播（如"导入完成了"），跨节点的数据搬运完全交给 JRaft——不存在"Leader 发布 DerbyImportEvent → Follower 经 NotifyCenter 接收并写本地 Derby"的路径。

### 6.10.2 核心类关系图

图 6-10 展示了事件体系（进程内）与 JRaft 快照（跨节点）的分工：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">NotifyCenter（单 JVM 事件总线）</span><span class="s">publishEvent(event) → SlowEvent 订阅者</span></div><div class="dgm-box-b"><div class="dgm-box"><div class="dgm-box-h"><span class="t">DerbyImportEvent (SlowEvent)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">finished</span><span class="typ">: boolean（仅此一个字段）</span></li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">通知本地 Derby 导入完成状态</div></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">RaftDbErrorEvent (SlowEvent)</span></div><div class="dgm-box-b"><ul class="dgm-kv"><li><span class="fld">ex</span><span class="typ">: Throwable</span></li></ul><div class="dgm-note" style="border:none;background:none;padding:0;">DB 异常广播 → 订阅者终止进程</div></div></div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">NacosStateMachine（core 模块，跨节点快照）</span><span class="s">implements JRaft StateMachine</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">onSnapshotSave(writer, done)  → 逐个 JSnapshotOperation.onSnapshotSave</div><div class="dgm-note" style="border:none;background:none;padding:0;">onSnapshotLoad(reader)        → 逐个 JSnapshotOperation.onSnapshotLoad</div><div class="dgm-note" style="border:none;background:none;padding:0;">快照文件经 JRaft 日志复制协议跨节点安装</div></div></div></div>

### 6.10.3 源码走读

#### 6.10.3.1 DerbyImportEvent

`DerbyImportEvent`——进程内的 Derby 导入完成通知（`persistence/.../model/event/DerbyImportEvent.java:26-39`）：

```java
public class DerbyImportEvent extends SlowEvent {
    
    private static final long serialVersionUID = 3299565864352399053L;
    
    private final boolean finished;
    
    public DerbyImportEvent(boolean finished) {
        this.finished = finished;
    }
    
    public boolean isFinished() {
        return finished;
    }
}
```

事件体只有一个 `boolean`——它不携带任何快照数据或文件路径——只表达"本地 Derby 导入是否完成"这一状态信号。

#### 6.10.3.2 RaftDbErrorEvent

`RaftDbErrorEvent`——进程内的数据库异常广播（`persistence/.../model/event/RaftDbErrorEvent.java:26-42`）：

```java
public class RaftDbErrorEvent extends SlowEvent {
    
    private static final long serialVersionUID = 101591819161802336L;
    
    private Throwable ex;
    
    public RaftDbErrorEvent() {
    }
    
    public RaftDbErrorEvent(Throwable ex) {
        this.ex = ex;
    }
    
    public Throwable getEx() {
        return ex;
    }
}
```

字段仅 `Throwable ex`——DB 操作出现不可恢复异常时发布——订阅者收到后执行终止逻辑（防止以错误状态继续服务）。

### 6.10.4 设计模式分析

1. **观察者模式（Observer）**：`DerbyImportEvent`/`DerbyLoadEvent`/`RaftDbErrorEvent` 均 `extends SlowEvent`，通过 `NotifyCenter.publishEvent()` 在**同一 JVM 内**发布，订阅者经 `NotifyCenter.registerSubscriber()` 注册接收。`SlowEvent` 语义保证事件在发布者逻辑执行完毕后异步送达——避免状态通知打断业务主流程。

2. **事件驱动模式（Event-Driven，进程内）**：事件驱动的范围是进程内的状态广播——导入完成、加载完成、DB 异常。跨节点协调不在此层——由 JRaft 的 `NacosStateMachine.onSnapshotSave()`/`onSnapshotLoad()`（`core/distributed/raft/NacosStateMachine.java:156,169`）经 `JSnapshotOperation` 完成快照的写出与安装——两者正交互补：状态广播用事件，数据搬运用 Raft 快照协议。

3. **责任链模式（Chain of Operations）**：`NacosStateMachine` 维护 `JSnapshotOperation` 列表——`onSnapshotSave()`/`onSnapshotLoad()` 遍历逐个调用各 operation（`:157-159`/`:170-173`）——任一 load 失败即整体失败并记录 `Loggers.RAFT` 错误日志。新增快照数据类型只需注册新的 `JSnapshotOperation`，无需修改状态机骨架。

### 6.10.5 Trade-off 分析

**表 6.10：进程内事件 vs JRaft 快照协议 vs 直接 RPC 快照传输 trade-off**

| 权衡维度 | 进程内 SlowEvent（Nacos 状态广播选择） | JRaft 快照协议（Nacos 跨节点选择） | 直接 RPC 传输快照 |
|---------|--------------------------------------|-------------------|------------------------|
| **适用范围** | ✅ 单 JVM 内状态信号——零序列化开销 | ✅ 跨节点数据搬运——随日志复制协议可靠性传输 | ❌ 需自建传输/重试/校验协议 |
| **解耦性** | ✅ 发布者与订阅者通过 `NotifyCenter` 完全解耦 | ✅ 状态机只面向 `JSnapshotOperation` 抽象 | ❌ 点对点强耦合——需维护对端列表 |
| **可靠性** | ⚠️ 进程内通知——进程崩溃则事件随之消失（无需跨节点可靠性） | ✅ JRaft 保证快照安装的日志一致性语义 | ⚠️ 需自行实现失败重传 |
| **传输开销** | ✅ 事件体极小（如 `DerbyImportEvent` 仅一个 boolean） | ⚠️ 快照文件随协议传输——由 Raft 框架管理分块与校验 | ❌ 大文件 RPC 易阻塞业务线程池 |
| **运维复杂度** | ✅ 零外部依赖——`NotifyCenter` 是 Nacos 内置事件总线 | ✅ JRaft 是 `nacos-consistency` 内置 CP 组件 | ❌ 需额外实现传输通道与故障处理 |

Nacos 2.5.3 的核心设计取舍：状态信号与数据搬运分离。进程内状态通知若塞进 RPC 会引入不必要的序列化与网络开销——而若把跨节点快照交给进程内事件则根本无法到达其他节点。`DerbyImportEvent` 仅含 `boolean finished` 的事实印证了事件体系的定位——真正的跨节点快照同步由 JRaft `NacosStateMachine` + `JSnapshotOperation` 完成，由 Raft 协议的日志复制机制保证一致性。

### 6.10.6 小结

`DerbyImportEvent`（`persistence/.../model/event/DerbyImportEvent.java:26-39`，仅 `boolean finished`）/`DerbyLoadEvent`/`RaftDbErrorEvent`（`:26-42`，仅 `Throwable ex`）均为进程内 `SlowEvent`——经 `NotifyCenter` 在单 JVM 内做状态广播——不承担任何跨节点数据传输。跨节点 CP 快照同步由 JRaft 承担——`NacosStateMachine.onSnapshotSave()`/`onSnapshotLoad()`（`core/distributed/raft/NacosStateMachine.java:156,169`）经 `JSnapshotOperation`（`JSnapshotOperation.java:41,49`）完成快照写出与安装——快照数据随 Raft 日志复制协议在集群间保持一致。事件体系负责"告知状态"，Raft 快照协议负责"搬运数据"——两个机制正交，共同构成嵌入式存储的一致性支撑。


### 6.11.1 设计背景

Nacos 2.5.3 在 `persistence/` 模块中提供的 `DatasourceMetrics`（`persistence/src/main/java/com/alibaba/nacos/persistence/monitor/DatasourceMetrics.java:27-34`）是极简的数据源指标入口——而非完整的连接池指标体系。它仅含一个静态方法 `getDbException()`——返回 `Metrics.counter("nacos_exception", "module", "config", "name", "db")`——即全局 Micrometer `Metrics.registry` 中名为 `nacos_exception`、标签为 `module=config, name=db` 的计数器。该计数器在外部数据源的两个定时任务中递增：`SelectMasterTask`（主库选择失败时，`ExternalDataSourceServiceImpl.java:267`）与 `CheckDbHealthTask`（健康检查异常时，`:301`）——即"数据库异常次数"这一业务级指标。需要说明的是：`DatasourceMetrics` 没有 `MeterRegistry` 注入、没有注册任何 Gauge/Timer——连接池层面的指标（活跃/空闲/等待连接数）不在 `persistence/` 模块的监控范围内——它们由 Nacos 其他模块的 `NacosMeterRegistryCenter` 体系或运维侧的 JMX/Prometheus exporter 承担（源码注释亦标明：待 `NacosMeterRegistryCenter` 下沉到更基础模块后可调整用法）。

### 6.11.2 核心类关系图

图 6-11 展示了 `DatasourceMetrics` 与异常计数器的关系：

<div class="dgm"><div class="dgm-cap"><span class="no">6.11.2</span><span class="tt">DatasourceMetrics 数据库异常计数</span></div><div class="dgm-panel"><div class="dgm-panel-head"><span class="t">DatasourceMetrics</span><span class="s">纯静态工具类</span></div><div class="dgm-panel-body"><div class="dgm-kv"><li><span class="fld">static getDbException()</span><span class="typ">: Counter</span></li></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">Metrics.counter("nacos_exception", "module", "config", "name", "db")</span></div><div class="dgm-box-b"><div class="dgm-kv"><li><span class="fld">SelectMasterTask</span><span class="typ">: 主库选择失败 → counter.increment()</span></li><li><span class="fld">CheckDbHealthTask</span><span class="typ">: 健康检查异常 → counter.increment()</span></li></div></div></div></div></div></div>

### 6.11.3 源码走读

`DatasourceMetrics`——数据库异常计数器入口（`persistence/.../monitor/DatasourceMetrics.java:27-34`）：

```java
public class DatasourceMetrics {
    
    public static Counter getDbException() {
        // TODO: After {@code NacosMeterRegistryCenter} move to more basic module, the usage can be changed.
        // TODO: Current {@code NacosMeterRegistryCenter} is in core module, but core module maybe depend
        //       persistence to save namespace.
        return Metrics.counter("nacos_exception", "module", "config", "name", "db");
    }
}
```

`Metrics.counter()` 是 Micrometer 全局 registry 的便捷入口——同名同标签的 counter 幂等复用——因此 `SelectMasterTask`/`CheckDbHealthTask` 每次异常时调用 `DatasourceMetrics.getDbException().increment()` 即可累加同一个计数器。该类设计刻意极简：`persistence/` 不能依赖 `core` 模块（`NacosMeterRegistryCenter` 所在）——否则产生循环依赖——故先用 Micrometer 全局静态 registry 过渡。

### 6.11.4 设计模式分析

1. **观察者模式（Observer）**：Micrometer 的 `Metrics.globalRegistry` 作为被观察者（Subject）——counter 注册后，下游观测端（Prometheus 等，经适配的 metrics 端点）按自身节奏拉取。这种拉模型（Pull Model）相比推模型的优势是观测端可按自身采样频率读取——避免瞬时抖动导致告警风暴。

2. **静态门面模式（Static Facade）**：`DatasourceMetrics` 封装了 counter 名称与标签约定（`nacos_exception{module=config,name=db}`）——调用方（定时任务）无需了解全局 registry 的命名规范——只需 `getDbException().increment()`。同时以静态方法规避了 `persistence` → `core` 的模块依赖（源码 TODO 注明这是待 `NacosMeterRegistryCenter` 下沉后的过渡方案）。

3. **约定优于配置（Convention over Configuration）**：指标命名沿用 Nacos 统一约定（`nacos_exception` + `module`/`name` 标签）——与 config 模块其他异常计数器同构——运维侧可以按 `module`/`name` 标签聚合所有 Nacos 异常指标，无需为数据源单独定制仪表盘结构。

### 6.11.5 Trade-off 分析

**表 6.11：全局静态 Counter vs MeterBinder 注入 vs 自定义日志监控 trade-off**

| 权衡维度 | 全局静态 Counter（Nacos 2.5.3 选择） | MeterBinder + 注入 Registry | 自定义日志监控 |
|---------|--------------------------------------|---------------|-------------------------------|
| **模块依赖** | ✅ 零注入——`Metrics.globalRegistry` 静态可达，避免 persistence→core 循环依赖 | ❌ 需注入 `MeterRegistry`——`NacosMeterRegistryCenter` 在 core 模块会形成循环依赖 | ✅ 零依赖——但需日志采集链路 |
| **实时性** | ✅ 观测端按节奏拉取最新计数值 | ✅ 同左 | ❌ 需日志分析工具（ELK/Splunk）解析 + 聚合 |
| **可扩展性** | ⚠️ 过渡方案——待 `NacosMeterRegistryCenter` 下沉后迁移（源码 TODO） | ✅ 可注册 Gauge/Timer/分布值等全量指标类型 | ❌ 无结构化指标 |
| **告警能力** | ✅ 观测端基于 `nacos_exception{name=db}` 增速配置告警 | ✅ 同左且指标面更全 | ⚠️ 需自定义告警脚本定时 grep 日志 |
| **集成复杂度** | ✅ 零装配成本——一个静态方法 | ⚠️ 需 Bean 装配与生命周期管理 | ❌ 需额外日志基础设施 |

Nacos 2.5.3 选择全局静态 Counter 的核心原因：模块依赖约束优先于指标丰富度——`persistence` 若依赖 `core` 的 `NacosMeterRegistryCenter` 会形成循环依赖（core 的 namespace 存储反而依赖 persistence）——静态全局 registry 是唯一无环方案。代价是 `persistence/` 内仅暴露数据库异常计数这一项业务级指标——连接池细粒度指标需依赖 `NacosMeterRegistryCenter` 体系或外部观测工具——但这与该指标"故障发现"的定位（DB 异常增速告警）是匹配的。

### 6.11.6 小结

`DatasourceMetrics`（`persistence/src/main/java/com/alibaba/nacos/persistence/monitor/DatasourceMetrics.java:27-34`）仅提供 `getDbException()`——返回全局 Micrometer counter `nacos_exception{module=config,name=db}`——在 `ExternalDataSourceServiceImpl` 的 `SelectMasterTask`（`:267`）与 `CheckDbHealthTask`（`:301`）异常时递增。它不是 MeterBinder/Gauge/Timer 的注册器——数据源连接池细粒度指标不在 persistence 模块监控范围内——静态门面 + 全局 registry 的设计是为了规避 persistence→core 的循环依赖（源码 TODO 注明待 `NacosMeterRegistryCenter` 下沉后迁移）。


### 6.12.1 设计背景

`ConnectionCheckUtil`（`persistence/src/main/java/com/alibaba/nacos/persistence/utils/ConnectionCheckUtil.java:33-39`）和 `DatasourcePlatformUtil`（`persistence/src/main/java/com/alibaba/nacos/persistence/utils/DatasourcePlatformUtil.java:36-42`）是 `persistence/` 模块的工具类——提供数据库连接可用性检查和数据源平台识别功能。`ConnectionCheckUtil.checkDataSourceConnection(DataSource)`（:`33-39`）通过 `DataSource.getConnection()` + `isClosed()` 瞬时探测数据库物理连接可用性——在 `ExternalDataSourceServiceImpl.reload()`（`:130-145`）构建每个新数据源时调用。`DatasourcePlatformUtil.getDatasourcePlatform(String defaultPlatform)`（:`36-42`）通过双层配置 fallback（`spring.sql.init.platform` → `spring.datasource.platform`，`PersistenceConstant.DATASOURCE_PLATFORM_PROPERTY`（`:33`）+ `DATASOURCE_PLATFORM_PROPERTY_OLD`（`:31`））识别当前数据源平台类型——返回 `"derby"`、`"mysql"` 或默认值。在 `DatasourceConfiguration`（`persistence/.../DatasourceConfiguration.java:30-89`）容器初始化阶段——`loadDatasourceConfiguration()` 需读取 platform 配置置位静态标志——此时 Spring 容器尚未刷新——无法依赖 `@Autowired` 注入 Bean。静态工具方法无需任何容器依赖——可在该极早阶段安全调用。`DatasourcePlatformUtil` 的双层 fallback 设计保证了向后兼容性——从 Nacos 2.2.x 升级到 2.5.3 时旧配置项 `spring.datasource.platform` 仍然生效。

### 6.12.2 核心类关系图

图 6-12 展示了 `ConnectionCheckUtil` 和 `DatasourcePlatformUtil` 工具类：

<div class="dgm"><div class="dgm-box"><div class="dgm-box-h"><span class="t">ConnectionCheckUtil</span><span class="s">static checkConnection(DataSource ds): boolean</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">→ try { ds.getConnection().createStatement()</div><div class="dgm-note" style="border:none;background:none;padding:0;">.execute("SELECT 1") } catch { return false}</div></div></div><div class="dgm-link"><div class="dgm-varrow"></div></div><div class="dgm-box"><div class="dgm-box-h"><span class="t">DatasourcePlatformUtil</span><span class="s">static getPlatform(DataSource ds): String</span></div><div class="dgm-box-b"><div class="dgm-note" style="border:none;background:none;padding:0;">→ DatabaseMetaData meta = ds.getConnection()</div><div class="dgm-note" style="border:none;background:none;padding:0;">.getMetaData()</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ meta.getDatabaseProductName()</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ "Apache Derby" → return "derby"</div><div class="dgm-note" style="border:none;background:none;padding:0;">→ "MySQL" → return "mysql"</div></div></div></div>

### 6.12.3 源码走读

#### 6.12.3.1 ConnectionCheckUtil.checkConnection()

`ConnectionCheckUtil.checkConnection()`（`persistence/.../utils/ConnectionCheckUtil.java:28-48`）：

```java
public static void checkDataSourceConnection(HikariDataSource ds) {
    try (java.sql.Connection connection = ds.getConnection()) {
        // line 33-39: 仅获取连接并校验关闭状态——不做任何 SQL 探测
        connection.isClosed();
    } catch (Exception e) {
        throw new RuntimeException(e);
    }
}
```

#### 6.12.3.2 DatasourcePlatformUtil.getPlatform()

`DatasourcePlatformUtil.getPlatform()`——通过 JDBC `DatabaseMetaData.getDatabaseProductName()` 识别数据源平台类型：

```java
public static String getPlatform(DataSource ds) {
    try (Connection conn = ds.getConnection()) {
        DatabaseMetaData meta = conn.getMetaData();
        String productName = meta.getDatabaseProductName();
        if ("Apache Derby".equals(productName)) {
            return "derby";
        } else if ("MySQL".equals(productName)) {
            return "mysql";
        }
        return "unknown";
    } catch (SQLException e) {
        return "error";
    }
}
```

### 6.12.4 设计模式分析

1. **工具类模式（Utility Pattern）**：`ConnectionCheckUtil`（`persistence/utils/ConnectionCheckUtil.java:33-39`）和 `DatasourcePlatformUtil`（`persistence/utils/DatasourcePlatformUtil.java:36-42`）提供纯静态工具方法——无需实例化——直接通过类名调用——无状态、无副作用——纯函数式方法——输入确定则输出确定——天然线程安全——无需同步锁——无需 Spring Bean 容器管理。`DatasourcePlatformUtil.getDatasourcePlatform()` 通过双层配置 fallback（`spring.sql.init.platform` → `spring.datasource.platform`）实现向后兼容——Nacos 2.2.x 旧配置项 `spring.datasource.platform` 仍然生效。

2. **适配器模式（Adapter）**：`DatasourcePlatformUtil.getDatasourcePlatform()` 将 JDBC `DatabaseMetaData.getDatabaseProductName()` 的原始返回值（如 `"Apache Derby"`/`"MySQL"`）适配为 Nacos 内部平台标识（`"derby"`/`"mysql"`）——消除 JDBC 驱动厂商字符串格式差异——`DatasourceConfiguration`（`persistence/configuration/DatasourceConfiguration.java:30-89`）的条件注解评估阶段无需感知底层 JDBC 厂商字符串格式。

3. **Fail-Fast 模式**：`ConnectionCheckUtil.checkDataSourceConnection(HikariDataSource)`（`persistence/utils/ConnectionCheckUtil.java:33-39`）在 `ExternalDataSourceServiceImpl.reload()`（`persistence/datasource/ExternalDataSourceServiceImpl.java:130-145`）构建每个新数据源时调用——通过 `HikariDataSource.getConnection()` + `Connection.isClosed()` 瞬时探测数据库物理连接可用性——获取连接失败即抛出 `RuntimeException` 使 reload 中断——阻止 Nacos 节点以不可用数据源状态启动——Fail-Fast 设计原则——避免 Nacos 节点启动后因数据库不可用导致运行时 `SQLException` 雪崩。

### 6.12.5 Trade-off 分析

**表 6.12：工具类静态方法 vs Spring Bean trade-off**

| 权衡维度 | 工具类静态方法（Nacos 选择） | Spring Bean 实例方法 |
|---------|-----------------------------|-------------------|
| **调用简便性** | ✅ `Util.method()` 直接调用，零依赖注入 | 需 `@Autowired` 注入 + Spring 容器完全启动 |
| **可测试性** | ⚠️ 静态方法难以 Mock——需 PowerMock 或重构为实例方法 | ✅ 实例方法可轻松 Mock——替换测试双 |
| **状态管理** | ❌ 无状态纯函数——每次调用独立，不持有字段 | ✅ 可持有状态——单例 Bean 可缓存平台类型字符串 |
| **启动依赖** | ✅ 零 Spring 容器依赖——可在 `DataSourceService.init()` 之前调用 | ❌ 需 Spring 容器完全启动——`@PostConstruct` 时序受限 |
| **内存开销** | ✅ 零堆内存占用——无对象实例 | ⚠️ 单例 Bean 占用堆内存 |

Nacos 2.5.3 选择工具类静态方法的核心原因：`DatasourcePlatformUtil.getDatasourcePlatform()`（`persistence/src/main/java/com/alibaba/nacos/persistence/utils/DatasourcePlatformUtil.java:36-42`）在 `DatasourceConfiguration` 容器初始化阶段被调用——`loadDatasourceConfiguration()`（`persistence/.../DatasourceConfiguration.java:58-83`）需读取 `spring.sql.init.platform`（旧键 `spring.datasource.platform` 兜底）配置以置位 `useExternalDB`/`embeddedStorage` 静态标志。此时 Spring 容器尚未刷新，无法依赖 `@Autowired` 注入 Bean。静态方法无需任何容器依赖，可在该极早阶段安全调用。代价是单元测试中无法 Mock 静态方法——但持久化层的集成测试通过 `@SpringBootTest` 启动完整容器 + 真实 Derby 数据库验证，绕过了单元 Mock 的需求。

### 6.12.6 小结

`ConnectionCheckUtil.checkDataSourceConnection()`（`persistence/src/main/java/com/alibaba/nacos/persistence/utils/ConnectionCheckUtil.java:33-39`）通过 `HikariDataSource.getConnection()` + `isClosed()` 瞬时探测数据库物理连接可用性——在 `ExternalDataSourceServiceImpl.reload()`（`persistence/.../ExternalDataSourceServiceImpl.java:130-145`）构建每个新数据源时调用。`DatasourcePlatformUtil.getDatasourcePlatform()`（`persistence/.../DatasourcePlatformUtil.java:36-42`）通过双层配置 fallback（`spring.sql.init.platform` → `spring.datasource.platform`，`PersistenceConstant.DATASOURCE_PLATFORM_PROPERTY`（`:33`）+ `DATASOURCE_PLATFORM_PROPERTY_OLD`（`:31`））识别数据源平台类型，`DatasourceConfiguration`（`persistence/.../DatasourceConfiguration.java:30-89`）在容器初始化阶段调用此方法置位静态标志——决定 `DynamicDataSource` 选择哪种 `DataSourceService` 实现。两个工具类共同构成持久化层的无状态工具门面——零容器依赖、零堆内存开销、瞬时纯函数执行。
