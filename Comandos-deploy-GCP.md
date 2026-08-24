## Paso 0: Vinculación
gcloud init

## Paso 1: Creación del repositorio
gcloud artifacts repositories create repositorio-backend-langchain-inmobiliaria  --repository-format docker --project datapath-ai17-adriana-alvarez --location us-central1


## Paso 3: Crear el repositorio de github

## Paso 4: Crear la Key de la Cuenta de Servicio en "IAM y Administración"

## Paso 5: Colocar el Service Account Key en GitHub Settings
Debes ir a "Secrets and variables"
Luego a "Actions"
Clic en "New repository secret"
El nombre del Secreto es "GCP_SERVICE_ACCOUNT_KEY"
En la caja de abajo copia y pega todo lo que está dentro de la Clave JSON que descargaste de la cuenta de servicio.

## Paso 6 - 1 Primer commit en tu Repo, Automatizacion:
git init                                                          # Inicia un repositorio Git en tu carpeta
git add .                                                         # Agrega TODOS los archivos al staging
git commit -m "Proyecto de automatización de despliegue en GCR"   # Crea el primer commit
git branch -M main                                                # Cambia el nombre de la rama a "main"
git remote add origin https://github.com/SU-USUARIO/SU-REPO.git   # Conecta con tu repositorio en GitHub
git push -u origin main   
                                        # Sube tu código a GitHub
## Paso 6 - 2 Automatizando nuevamente:
rm -rf /ws/code/.git

## Cuando deseas volver a subir por algun error corres lo siguiente:
git status
git add .
git commit -m "Ajustes en workflow de CI/CD 2"
git push