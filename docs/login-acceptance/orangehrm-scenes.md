| Scene | Loại | Feature | Quay | Trang đích | Trang clip thực sự hiển thị | Đúng trang | Frame login | no_target |
|---|---|---|---|---|---|---|---|---|
| s1 | hook |  | screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s2 | feature_demo | dashboard_overview | recording | `/web/index.php/dashboard/index` | `/web/index.php/dashboard/index` | có | 0/4 |  |
| s3 | feature_demo | dashboard_overview | None | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s4 | feature_demo | leave_management | recording | `/web/index.php/dashboard/index` | `/web/index.php/dashboard/index` | có | 0/4 |  |
| s5 | before_after |  | screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s6 | cta |  | recording | `/web/index.php/dashboard/index` | `/web/index.php/dashboard/index` | có | 0/4 |  |

```json
{
  "scenes": 6,
  "real_clips": 3,
  "no_target_scenes": 0,
  "scenes_on_login_page": 0,
  "demo_scenes": 3,
  "demo_showing_their_page": 2,
  "guard": {
    "allow_mutations": false,
    "blocked": {
      "post_default": 6
    },
    "allowed": {},
    "faked_204": {},
    "login_phase": {
      "posts_allowed": {},
      "hosts_refused": {}
    },
    "first_blocked_urls": [
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push",
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push",
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push",
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push",
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push",
      "POST https://opensource-demo.orangehrmlive.com/web/index.php/events/push"
    ],
    "first_passed_urls": {}
  },
  "login_phase_explore": {
    "posts_allowed": {},
    "hosts_refused": {}
  },
  "sensitive_skipped": [
    "https://opensource-demo.orangehrmlive.com/web/index.php/admin/viewAdminModule"
  ],
  "pages_seen_by_explore": [
    "https://opensource-demo.orangehrmlive.com/web/index.php/dashboard/index",
    "https://opensource-demo.orangehrmlive.com/web/index.php/pim/viewEmployeeList"
  ]
}
```
