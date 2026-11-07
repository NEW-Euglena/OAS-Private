"""使用模拟设备和通知回放登录恢复、异常重启及调度过程。"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from script import Script
from module.script import ScriptRuntimeController, ScriptRuntimeDecision
from module.exception import (
    GameBugError, GameNotRunningError, GamePageUnknownError,
    GameStuckError, GameTooManyClickError, RequestHumanTakeover, TaskEnd,
)
from tasks.Component.Login.service import LoginService
from tasks.Restart.config import RestartConfig
from tasks.Restart.script_task import ScriptTask


class ErrorRestartTests(unittest.TestCase):
    def make_script(self, limit=1):
        script = Script.__new__(Script)
        script.config_name = '测试'
        script._error_restart_count = 0
        script._error_restart_pending = False
        script._desktop_login_count = 0
        script._login_retry_pending = False
        script.last_task_runtime_outcome = None
        script.config = Mock()
        script.config.task_runtime_outcome = None
        script.config.model.restart.restart_config = SimpleNamespace(error_restart_limit=limit)
        script.config.model.restart.scheduler.enable = True
        script.device = Mock(is_desktop=True)
        script.device.desktop_window_exists.return_value = True
        script.device.app_is_running.return_value = False
        script.device.find_desktop_login_popup.return_value = True
        script.save_error_log = Mock()
        script.exception_handler = Mock()
        script._register_page_unknown_failure = Mock(return_value=None)
        return script

    def test_config_accepts_zero_and_normalizes_negative(self):
        self.assertEqual(RestartConfig().error_restart_limit, 1)
        self.assertEqual(RestartConfig(error_restart_limit=0).error_restart_limit, 0)
        self.assertEqual(RestartConfig(error_restart_limit=-1).error_restart_limit, 1)

    def test_each_recoverable_error_stops_before_second_restart(self):
        for error in (GameNotRunningError, GameStuckError, GameTooManyClickError,
                      GameBugError, GamePageUnknownError):
            with self.subTest(error=error.__name__):
                script = self.make_script()
                script.desktop_login_recovery = Mock(return_value=False)
                script._handle_task_exception(error(), 'Pets')
                self.assertEqual(script._error_restart_count, 1)
                with self.assertRaises(SystemExit):
                    script._handle_task_exception(error(), 'Pets')
                script.config.task_call.assert_called_once_with('Restart', force_call=False)

    def test_zero_and_disabled_restart_do_not_schedule(self):
        for limit, enabled in ((0, True), (1, False)):
            with self.subTest(limit=limit, enabled=enabled):
                script = self.make_script(limit)
                script.config.model.restart.scheduler.enable = enabled
                with self.assertRaises(SystemExit):
                    script._handle_task_exception(GameTooManyClickError(), 'Pets')
                self.assertIn('GameTooManyClickError', script.config.notifier.push.call_args_list[0].kwargs['content'])
                script.config.task_call.assert_not_called()

    def test_budget_is_shared_between_tasks_and_survives_success(self):
        script = self.make_script()
        script._request_error_restart('Pets')
        script._handle_task_exception(TaskEnd(), 'Restart')
        with self.assertRaises(SystemExit):
            script._request_error_restart('DailyTrifles')

    def test_pending_restart_precedes_overdue_tasks(self):
        script = self.make_script()
        script._error_restart_pending = True
        self.assertEqual(script.get_next_task(), 'Restart')
        script.config.get_next.assert_not_called()

    def test_first_recovery_is_not_skipped_and_clears_pending_after_success(self):
        script = self.make_script()
        script._error_restart_pending = True
        script.is_first_task = True
        script.resource_precache_enable = False
        script.anti_ban_guard = Mock()
        script.runtime = Mock()
        script.runtime.prepare_task_execution.return_value = ScriptRuntimeDecision.READY
        script.device.is_desktop = False
        script.config.script.device.run_background_only = True
        script.config.request_scheduler_stop = False
        script.config.pending_task = [Mock()]
        script.config.waiting_task = []
        script._reset_page_unknown_backoff = Mock()
        script.failure_record = {}

        def recover(command):
            script.config.pending_task = []
            return True

        script.run = Mock(side_effect=recover)
        with patch('script.Cooperation'), patch('script.logger'), \
                patch('script.RuleScatter'), patch('script.del_cached_property'):
            script.loop()
        script.run.assert_called_once_with('Restart')
        script.config.task_delay.assert_not_called()
        self.assertFalse(script._error_restart_pending)

    def test_custom_limit_allows_exact_number_of_restarts(self):
        script = self.make_script(limit=3)
        for _ in range(3):
            script._request_error_restart('Pets')
            script._error_restart_pending = False
        with self.assertRaises(SystemExit):
            script._request_error_restart('Pets')
        self.assertEqual(script.config.task_call.call_count, 3)

    def test_desktop_internal_start_attempts_remain_independent(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(model=SimpleNamespace(restart=SimpleNamespace(
            restart_config=SimpleNamespace(error_restart_limit=1))))
        task.device = Mock()
        task.device.app_start.side_effect = GameNotRunningError()
        with self.assertRaises(RequestHumanTakeover):
            task._desktop_start_and_login()
        self.assertEqual(task.device.app_start.call_count, 3)

    def test_login_internal_failure_keeps_upstream_recovery_behavior(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                login = LoginService.__new__(LoginService)
                login.config = SimpleNamespace(model=SimpleNamespace(restart=SimpleNamespace(
                    restart_config=SimpleNamespace(error_restart_limit=1))))
                login.device = Mock(is_desktop=desktop)
                login._app_handle_login = Mock(side_effect=GameStuckError())
                with self.assertRaises(RequestHumanTakeover):
                    login.app_handle_login()
                login.device.app_stop.assert_called_once()
                login.device.app_start.assert_called_once()

    def test_replay_login_then_first_real_error_keeps_restart_available(self):
        script = self.make_script()
        with patch('tasks.Component.Login.service.LoginService') as login:
            self.assertTrue(script._handle_task_exception(GameNotRunningError(), 'DemonEncounter'))
        login.return_value.app_handle_login.assert_called_once()
        self.assertEqual(script._error_restart_count, 0)
        self.assertTrue(script._login_retry_pending)
        script.config.task_call.assert_not_called()
        script._handle_task_exception(GameTooManyClickError('blank_close'), 'DemonEncounter')
        self.assertEqual(script._error_restart_count, 1)
        script.config.task_call.assert_called_once_with('Restart', force_call=False)

    def test_original_error_is_notified_before_limit_notification(self):
        for error in (GameTooManyClickError, GameStuckError, GamePageUnknownError):
            with self.subTest(error=error.__name__):
                script = self.make_script()
                script._error_restart_count = 1
                with self.assertRaises(SystemExit):
                    script._handle_task_exception(error(), 'Pets')
                contents = [call.kwargs['content'] for call in script.config.notifier.push.call_args_list]
                self.assertEqual(len(contents), 2)
                self.assertIn(error.__name__, contents[0])
                self.assertIn('上限 1 次', contents[1])
                script.config.task_call.assert_not_called()

    def test_original_error_is_notified_before_scheduling_restart(self):
        script = self.make_script()
        events = Mock()
        events.attach_mock(script.config.notifier.push, 'notify')
        events.attach_mock(script.config.task_call, 'restart')
        script._handle_task_exception(GameTooManyClickError(), 'Pets')
        self.assertEqual([call[0] for call in events.mock_calls], ['notify', 'restart'])

    def test_login_recovery_does_not_require_enabled_restart_or_budget(self):
        script = self.make_script(limit=0)
        script.config.model.restart.scheduler.enable = False
        with patch('tasks.Component.Login.service.LoginService'):
            self.assertTrue(script._handle_task_exception(GameNotRunningError(), 'Pets'))
        self.assertEqual(script._error_restart_count, 0)
        script.config.task_call.assert_not_called()

    def test_login_window_loss_escalates_to_one_restart(self):
        script = self.make_script()
        with patch('tasks.Component.Login.service.LoginService') as login:
            login.return_value.app_handle_login.side_effect = GameNotRunningError()
            script._handle_task_exception(GameNotRunningError(), 'Pets')
        self.assertEqual(script._error_restart_count, 1)
        script.config.task_call.assert_called_once_with('Restart', force_call=False)

    def test_repeated_login_is_limited_separately_and_success_resets_it(self):
        script = self.make_script()
        with patch('tasks.Component.Login.service.LoginService') as login:
            for _ in range(3):
                self.assertTrue(script.desktop_login_recovery('Pets'))
            self.assertFalse(script.desktop_login_recovery('Pets'))
            self.assertEqual(login.return_value.app_handle_login.call_count, 3)
        self.assertEqual(script._error_restart_count, 0)
        script._handle_task_exception(TaskEnd(), 'Pets')
        self.assertEqual(script._desktop_login_count, 0)

    def test_human_takeover_during_login_is_not_swallowed(self):
        script = self.make_script()
        with patch('tasks.Component.Login.service.LoginService') as login:
            login.return_value.app_handle_login.side_effect = RequestHumanTakeover()
            with self.assertRaises(SystemExit):
                script.desktop_login_recovery('Pets')
        script.config.task_call.assert_not_called()

    def test_healthy_desktop_and_emulator_do_not_enter_direct_login(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                script = self.make_script()
                script.device.is_desktop = desktop
                script.device.app_is_running.return_value = True
                script.device.find_desktop_login_popup.return_value = False
                with patch('tasks.Component.Login.service.LoginService') as login:
                    self.assertFalse(script.desktop_login_recovery('Pets'))
                login.assert_not_called()

    def test_pending_flags_are_reported_and_login_flag_clears_before_next_task(self):
        script = self.make_script()
        script._login_retry_pending = True
        self.assertTrue(script.recovery_pending)
        script._reset_task_runtime_outcome()
        self.assertFalse(script.recovery_pending)
        script._error_restart_pending = True
        script._reset_task_runtime_outcome()
        self.assertTrue(script.recovery_pending)

    def test_desktop_recovery_does_not_query_adb_lifecycle(self):
        task = ScriptTask.__new__(ScriptTask)
        task.device = Mock(is_desktop=True)
        task.app_restart = Mock()
        task.recover_app()
        task.app_restart.assert_called_once()
        task.device.app_is_alive.assert_not_called()
        task.device.app_is_running.assert_not_called()

    def test_restart_queued_during_idle_wait_is_selected_immediately(self):
        script = self.make_script()
        script.config.get_next.return_value = SimpleNamespace(
            command='Pets', next_run=datetime.now() + timedelta(hours=1))
        script.state_queue = None
        script.task_hoarding_until = None
        script.anti_ban_guard = Mock()
        script.anti_ban_guard.wake_time.return_value = None
        script.anti_ban_guard.sleep_wake_at.return_value = None
        script._hoard_next_task = Mock(side_effect=lambda task, now: task)
        script._reset_continuous_task_rest = Mock()
        script.runtime = Mock()

        def request_restart(wait_until):
            script._error_restart_pending = True
            return ScriptRuntimeDecision.RESCHEDULE

        script.runtime.handle_wait_during_idle.side_effect = request_restart
        with patch('script.del_cached_property'):
            self.assertEqual(script.get_next_task(), 'Restart')
        script.config.get_next.assert_called_once()
        script.runtime.handle_wait_during_idle.assert_called_once()

    def test_existing_maintenance_and_page_unknown_backoff_take_precedence(self):
        for maintenance in (False, True):
            with self.subTest(maintenance=maintenance):
                script = self.make_script()
                script._delay_tasks_for_server_update = Mock(return_value=maintenance)
                target = datetime.now() + timedelta(minutes=30)
                script._register_page_unknown_failure.return_value = target
                script._enter_page_unknown_backoff = Mock()
                self.assertFalse(script._handle_task_exception(GamePageUnknownError(), 'GotoMain'))
                script.config.task_call.assert_not_called()
                if maintenance:
                    script._enter_page_unknown_backoff.assert_not_called()
                else:
                    script._enter_page_unknown_backoff.assert_called_once_with(target)


class RuntimeRecoveryTests(unittest.TestCase):
    def make_runtime(self):
        script = ErrorRestartTests().make_script()
        runtime = ScriptRuntimeController(script)
        runtime._ensure_emulator_running = Mock()
        runtime._wait_for_server_update_window = Mock(return_value=ScriptRuntimeDecision.READY)
        runtime._consume_server_update_delay_outcome = Mock(return_value=None)
        script.run = Mock(return_value=True)
        return script, runtime

    def test_task_preparation_logs_in_without_restart(self):
        script, runtime = self.make_runtime()
        with patch('tasks.Component.Login.service.LoginService'):
            self.assertEqual(runtime.prepare_task_execution('Pets'), ScriptRuntimeDecision.READY)
        self.assertEqual(script._error_restart_count, 0)
        script.run.assert_not_called()

    def test_idle_cold_start_logs_in_without_consuming_restart_budget(self):
        script, runtime = self.make_runtime()
        with patch('tasks.Component.Login.service.LoginService'):
            self.assertEqual(runtime._ensure_game_running(), ScriptRuntimeDecision.READY)
        self.assertEqual(script._error_restart_count, 0)
        script.run.assert_not_called()

    def test_idle_goto_main_returns_to_scheduler_for_both_pending_recoveries(self):
        for pending in ('_error_restart_pending', '_login_retry_pending'):
            with self.subTest(pending=pending):
                script, runtime = self.make_runtime()
                script.device.app_is_running.return_value = True
                setattr(script, pending, True)
                self.assertEqual(runtime._ensure_game_running(require_main=True), ScriptRuntimeDecision.RESCHEDULE)

    def test_missing_window_uses_normal_startup_without_spending_error_budget(self):
        script, runtime = self.make_runtime()
        script.device.desktop_window_exists.return_value = False
        script.device.app_is_running.side_effect = [False, True]
        self.assertEqual(runtime.prepare_task_execution('Pets'), ScriptRuntimeDecision.RESCHEDULE)
        script.run.assert_called_once_with('Restart')
        self.assertEqual(script._error_restart_count, 0)


if __name__ == '__main__':
    unittest.main()
