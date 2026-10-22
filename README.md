# plan-chasse
Plan Chasse : téléchargement de l'application Android (APK)

## Plan de chasse (mise à jour automatique)

Chaque nuit, la tâche « Plan de chasse » (`.github/workflows/plan.yml`) exporte les zones de chasse publiées par
l'Agence Nationale des Eaux et Forêts (service public `sigdef.eauxetforets.gov.ma`), les contrôle, puis publie le
plan dans la release `plan-data` **uniquement s'il a changé**. L'application lit `manifest.json` au premier lancement
de chaque jour et télécharge le nouveau plan.

Garde-fous : rien n'est publié si l'export est incomplet, si une réserve disparaît ou si plus de 2 % des zones
disparaissent ; la tâche échoue alors et un e-mail est envoyé pour vérification.

Ne pas supprimer la release `plan-data`.
