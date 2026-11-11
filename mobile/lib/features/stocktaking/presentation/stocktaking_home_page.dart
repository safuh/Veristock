import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../auth/models/organization.dart';

class StocktakingHomePage extends StatelessWidget {
  const StocktakingHomePage({
    super.key,
    required this.identifier,
    required this.organizations,
    required this.selectedOrganization,
    required this.onOrganizationChanged,
    required this.onSignOut,
  });

  final String identifier;
  final List<Organization> organizations;
  final Organization selectedOrganization;
  final ValueChanged<Organization> onOrganizationChanged;
  final VoidCallback onSignOut;

  Future<void> _openScanner(BuildContext context) async {
    final barcode = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(
        builder: (_) => const _BarcodeScannerPage(),
      ),
    );
    if (context.mounted && barcode != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Scanned barcode: $barcode')),
      );
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Veristock Field'),
          actions: [
            IconButton(
              tooltip: 'Sign out',
              onPressed: onSignOut,
              icon: const Icon(Icons.logout),
            ),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text('FIELD OPERATIONS',
                style: Theme.of(context).textTheme.labelSmall),
            const SizedBox(height: 6),
            Text('Ready for stocktaking',
                style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 18),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('ACTIVE ORGANIZATION'),
                    const SizedBox(height: 8),
                    DropdownButtonFormField<Organization>(
                      initialValue: selectedOrganization,
                      isExpanded: true,
                      items: organizations
                          .map((organization) => DropdownMenuItem(
                                value: organization,
                                child: Text(organization.displayName,
                                    overflow: TextOverflow.ellipsis),
                              ))
                          .toList(),
                      onChanged: (organization) {
                        if (organization != null) {
                          onOrganizationChanged(organization);
                        }
                      },
                    ),
                    const SizedBox(height: 8),
                    Text('Signed in as $identifier',
                        style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Card(
              child: ListTile(
                leading: const CircleAvatar(
                  child: Icon(Icons.qr_code_scanner),
                ),
                title: const Text('Test barcode scanner'),
                subtitle: const Text(
                    'Camera scanning foundation; count submission is not connected yet.'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _openScanner(context),
              ),
            ),
            const SizedBox(height: 16),
            const _FeatureTile(
              icon: Icons.assignment_outlined,
              title: 'Assigned stocktakes',
              detail: 'Task assignment and count-round APIs are next.',
            ),
            const _FeatureTile(
              icon: Icons.cloud_sync_outlined,
              title: 'Offline synchronization',
              detail:
                  'Queued count capture will be enabled after encrypted storage and conflict handling are implemented.',
            ),
            const _FeatureTile(
              icon: Icons.camera_alt_outlined,
              title: 'Vision-assisted counting',
              detail:
                  'Camera evidence and AI-assisted item matching will be added to the count workflow.',
            ),
          ],
        ),
      );
}

class _FeatureTile extends StatelessWidget {
  const _FeatureTile({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => Card(
        child: ListTile(
          leading: Icon(icon),
          title: Text(title),
          subtitle: Text(detail),
        ),
      );
}

class _BarcodeScannerPage extends StatefulWidget {
  const _BarcodeScannerPage();

  @override
  State<_BarcodeScannerPage> createState() => _BarcodeScannerPageState();
}

class _BarcodeScannerPageState extends State<_BarcodeScannerPage> {
  bool _handled = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Barcode scanner')),
        body: MobileScanner(
          onDetect: (capture) {
            if (_handled || capture.barcodes.isEmpty) return;
            final value = capture.barcodes.first.rawValue;
            if (value == null || value.isEmpty) return;
            _handled = true;
            Navigator.of(context).pop(value);
          },
        ),
      );
}
