"""Read-only permission/receipt view and explicit operator Configuration actions."""

from .errors import UserError
from .maintenance_policy import ACTIONS, SCAN_CADENCES
from .maintenance_projection import summary


class MaintenanceConfiguration:
    def maintenance_configuration(self, receipt=None):
        from .maintenance import POLICY_ACCEPTED

        records = [row for row in self.store.all('settings') if isinstance(row, dict)]
        if receipt:
            return self.maintenance_scan_run(receipt)
        index = {row.get('id'): row for row in records if row.get('id')}
        tasks = self.store.all('tasks')
        rules = [dict(rule, operational=summary(self, rule, index, tasks)) for rule in self.maintenance_rules()]
        return dict(
            policy_accepted=POLICY_ACCEPTED,
            machine_paused=self.store.get('settings', 'maintenance-paused:machine', True),
            libraries=[
                dict(
                    id=row['id'],
                    title=row['title'],
                    roots=[m['plex_root'] for m in row.get('mappings', [])],
                    paused=self.store.get('settings', 'maintenance-paused:' + row['id'], False),
                    caps=self.maintenance_caps(row['id']),
                )
                for row in self.store.all('libraries')
            ],
            machine_caps=self.maintenance_caps(),
            rules=rules,
            cached_assets=[
                dict(
                    id=row['id'],
                    library=row['library'],
                    title=row.get('title') or 'Untitled media item',
                    available=bool(row.get('present', True)),
                )
                for row in self.store.all('assets')
            ],
            actions=sorted(ACTIONS),
            cadences=list(SCAN_CADENCES),
            receipts=sorted(
                [row for row in records if row.get('record_type') in {'maintenance_scan', 'maintenance_decision'}],
                key=lambda row: row.get('created', ''),
                reverse=True,
            )[:100],
            limitations=[
                'Automatic local AI needs independently verified local-only model/digest evidence and is unavailable.',
                'Separate-output processing requires verified local tools/model artifacts and hard output-file limits.',
                'Scans require two matching complete inventories within explicit catalogue/page/time caps. Oversized, incomplete or unstable inventories cause no media probes.',
                'Only post-activation new identities qualify. Old catalogue, rematches and ambiguous copies remain manual.',
                'Metadata/cast/artwork saves, paid generation, publication, renaming, deletion, cleanup and export always remain manual.',
            ],
        )

    def maintenance_configuration_action(self, data):
        action = data.get('operation')
        if action == 'save_rule':
            result = self.save_maintenance_rule(data.get('id'), data['revision'], data['values'])
        elif action == 'save_caps':
            result = self.save_maintenance_caps(data.get('library'), data['revision'], data['values'])
        elif action == 'preview':
            result = self.preview_maintenance_enable(data['id'], data['revision'])
        elif action == 'enable':
            result = self.enable_maintenance_rule(data['preview'], data['digest'], data['action'])
        elif action in {'pause', 'resume', 'disable'}:
            result = self.change_maintenance_state(data['id'], data['revision'], action)
        elif action == 'scope_pause':
            result = self.pause_maintenance_scope(data.get('library'), data['paused'])
        else:
            raise UserError('Choose a supported explicit maintenance configuration action')
        self.ensure_maintenance_scheduler()
        return result
