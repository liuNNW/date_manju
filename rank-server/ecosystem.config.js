/**
 * PM2 配置
 * ----------
 *   pm2 start ecosystem.config.js
 *   pm2 restart drama-rank
 *   pm2 logs drama-rank
 *   pm2 save && pm2 startup      # 开机自启
 *
 * 反代指向 127.0.0.1:6066 即可（只监听回环，不直接暴露公网）。
 */
module.exports = {
  apps: [
    {
      name: 'drama-rank',
      script: 'server.js',
      cwd: __dirname,

      // 单实例即可：多实例会各自重复抓取，白费流量
      exec_mode: 'fork',
      instances: 1,

      autorestart: true,
      max_restarts: 20,
      min_uptime: '60s',
      restart_delay: 3000,
      max_memory_restart: '400M',
      kill_timeout: 8000,
      wait_ready: false,

      // 时区与 Node 参数
      env: {
        NODE_ENV: 'production',
        PORT: 6066,
        HOST: '127.0.0.1',        // 只监听本机，公网交给你的反代
        REFRESH_LIGHT: 300,       // 轻量刷新：5 分钟
        REFRESH_HEAVY: 21600,     // 含分集全量：6 小时
        // ADMIN_TOKEN: 'change-me',  // 需要 /api/refresh 保护时打开
        TZ: 'Asia/Shanghai',
      },

      out_file: 'logs/out.log',
      error_file: 'logs/err.log',
      merge_logs: true,
      time: true,

      // 忽略数据目录，避免 watch 模式下无限重启
      ignore_watch: ['data', 'logs', 'node_modules'],
      watch: false,
    },
  ],
};
