# Sécurité

Atlas Musical est une application locale destinée à écouter sur `127.0.0.1`. Elle ne doit pas être exposée sur Internet : le serveur n’embarque ni authentification ni limitation d’accès.

## Signaler une vulnérabilité

Utiliser de préférence l’onglet **Security → Report a vulnerability** du dépôt GitHub afin de garder le signalement privé. Indiquer la version, les étapes de reproduction et l’impact estimé. Éviter de publier un exploit ou des données personnelles dans une issue publique.

## Périmètre

Sont particulièrement concernés :

- le service de fichiers audio et les exports ;
- la validation des annotations ;
- l’écriture SQLite et les noms de fichiers exportés ;
- l’intégration locale Omarchy.
