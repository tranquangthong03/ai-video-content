| Scene | Loại | Feature | Quay | Trang đích | Trang clip thực sự hiển thị | Đúng trang | Frame login | no_target |
|---|---|---|---|---|---|---|---|---|
| s1 | hook |  | screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s2 | feature_demo | apply_leave | fallback_screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s3 | feature_demo | apply_leave | fallback_screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s4 | feature_demo | leave_approval_queue | fallback_screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s5 | feature_demo | leave_approval_queue | fallback_screenshot | `/web/index.php/dashboard/index` | — | — | 0/0 |  |
| s6 | cta |  | recording | `/web/index.php/dashboard/index` | `/web/index.php/dashboard/index` | có | 0/2 |  |

```json
{
  "scenes": 6,
  "real_clips": 1,
  "no_target_scenes": 0,
  "scenes_on_login_page": 0,
  "demo_scenes": 4,
  "demo_showing_their_page": 0,
  "guard": {
    "allow_mutations": false,
    "blocked": {
      "post_default": 8
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
