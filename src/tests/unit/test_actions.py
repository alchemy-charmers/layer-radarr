import imp

import mock


class TestActions():
    def test_disable_auth_action(self, radarr, monkeypatch):
        mock_function = mock.Mock()
        monkeypatch.setattr(radarr, 'modify_config', mock_function)
        assert mock_function.call_count == 0
        imp.load_source('disable-auth', './actions/disable-auth')
        assert mock_function.call_count == 1
