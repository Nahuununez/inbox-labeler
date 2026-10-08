# inbox-labeler

Etiqueta automáticamente tu bandeja de entrada de Gmail (ofertas de empleo, bancos, promociones, recibos, redes sociales…) con **reglas que vos escribís** y, opcionalmente, **Gemini** como respaldo para lo que ninguna regla reconoce. Corre solo, gratis y sin servidor, con GitHub Actions.

> **English summary.** A small Python tool that labels your Gmail INBOX using your own keyword/sender rules (`rules.yaml`), with an optional Gemini fallback for messages no rule matches. It runs on a schedule with GitHub Actions. It **only adds labels**: it never deletes, archives or marks mail as read, and it reads only the `From` and `Subject` headers, never the body. Use it as a **private** copy (button *Use this template* → *Private*), follow the setup below (Google Cloud OAuth client → refresh token → GitHub secrets), and start with a dry run. Without a Gemini key, or with `USE_GEMINI=false`, no email data is sent to anyone. Docs are in Spanish; the code, comments and `rules.yaml` descriptions are in English.

## Qué hace

Cada día (o cuando vos lo ejecutes) mira los mensajes recientes de la bandeja de entrada y les agrega **una etiqueta**:

```
Remitente: jobs-noreply@linkedin.com    Asunto: New job alert: Data Analyst   →  Jobs-Offers
Remitente: service@paypal.com           Asunto: You sent a payment of $20     →  Banking-Transactional
Remitente: newsletter@shoes.example     Asunto: Summer sale: 40% off          →  Promotions
Remitente: alice@example.com            Asunto: Dinner on Friday?             →  (sin etiqueta)
```

1. Primero aplica tus **reglas** (`rules.yaml`): rápido, gratis y predecible.
2. Si ninguna regla coincide y activaste Gemini, le pregunta a **Gemini** (solo remitente y asunto) y acepta la respuesta únicamente si tiene alta confianza. Ante la duda, no etiqueta.

## Garantías de seguridad

Estas propiedades están en el código y cubiertas por tests (`python -m tests`):

- **Solo agrega etiquetas.** Nunca borra, archiva, marca como leído ni saca mensajes de la bandeja.
- **No lee el cuerpo de tus mails.** Pide a Gmail únicamente las cabeceras `From` y `Subject`.
- **Vista previa por defecto.** Sin `--apply` no se modifica nada. Las ejecuciones manuales en GitHub Actions también son vista previa salvo que marques *apply*.
- **Las corridas programadas no crean etiquetas.** Crear etiquetas es un paso aparte y explícito.
- **Los logs no filtran tu correo.** El log y el resumen de cada corrida tienen solo contadores e ids de mensaje, nunca remitentes ni asuntos. `--verbose` (que sí los imprime) está bloqueado dentro de GitHub Actions.
- **Gemini es opcional.** Sin `GEMINI_API_KEY`, o con `USE_GEMINI=false`, no se envía ningún dato a Gemini.

## Privacidad: lo que debés saber

- Con Gemini activado, **el remitente y el asunto** de los mensajes que ninguna regla reconoció se envían a la API de Gemini de Google. El cuerpo nunca se envía.
- Con una API key del nivel gratuito, Google puede usar los datos enviados para mejorar sus productos. **Revisá los términos vigentes de la Gemini API** antes de activarlo. Si no querés eso, usá modo solo-reglas (no pongas la key o definí `USE_GEMINI=false`).
- El permiso que le das al proyecto (`gmail.modify`) es el que Gmail exige para aplicar etiquetas a mensajes, pero **da acceso de lectura y escritura a todo tu correo**. El código solo usa lo descrito arriba, pero el token puede más. Por eso:
  - **Usá una copia privada de este repositorio**, nunca pública.
  - Activá verificación en dos pasos en tu cuenta de GitHub y no agregues colaboradores en los que no confíes (quien pueda editar los workflows podría usar tus secretos).
  - Podés revocar el acceso cuando quieras en <https://myaccount.google.com/permissions>.
- Tu `rules.yaml` describe tus hábitos (bancos, tiendas, búsqueda laboral). Es otra razón para mantener tu copia privada.

## Requisitos

- Una cuenta de Gmail y una cuenta de GitHub.
- Python 3.12 o superior en tu computadora para el paso único de autorización (probado con 3.12 y 3.13).
- Una cuenta de Google Cloud (el proyecto gratuito alcanza; no hace falta facturación para Gmail API).
- Opcional: una API key de Gemini (Google AI Studio).

## Instalación paso a paso

### 1. Creá tu copia privada

En esta página usá **Use this template → Create a new repository** y elegí **Private**.
Si el botón no aparece, clonalo y subilo a un repositorio privado tuyo:

```bash
git clone https://github.com/<usuario-original>/inbox-labeler.git
cd inbox-labeler
git remote set-url origin https://github.com/<tu-usuario>/inbox-labeler.git
git push -u origin main
```

### 2. Creá las credenciales de Google

Los nombres de los menús de Google Cloud cambian con frecuencia; buscá los términos en inglés.

1. En <https://console.cloud.google.com/> creá un proyecto nuevo.
2. Habilitá **Gmail API** (APIs & Services → Library).
3. Configurá la **pantalla de consentimiento / Google Auth Platform**: tipo *External*, nombre de app a gusto, tu email como contacto. Agregá tu propio email como **usuario de prueba** y el scope `.../auth/gmail.modify`.
4. En **Credentials → Create credentials → OAuth client ID**, tipo **Desktop app**. Descargá el JSON y guardalo en la carpeta del proyecto como `client_secret.json` (Google lo descarga con un nombre largo: renombralo).

> **Importante: vencimiento del token.** Mientras la app esté en estado *Testing*, Google vence el refresh token a los **7 días aproximadamente** y las corridas empezarán a fallar con `invalid_grant`. Para uso personal, pasá la app a **In production** desde la misma pantalla de consentimiento. Como la app es solo tuya y no está verificada, Google mostrará una advertencia al autorizar; es esperable. Confirmá estos detalles en la documentación de Google, que puede cambiar.

### 3. Obtené el token (una sola vez, en tu computadora)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m inbox_labeler token
```

Se abre el navegador, aceptás los permisos y la terminal imprime tres valores: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` y `GMAIL_REFRESH_TOKEN`. **Tratalos como contraseñas**: no los pegues en chats, issues ni commits.

### 4. (Opcional) API key de Gemini

Creala en <https://aistudio.google.com/>. Si preferís no enviar nada a Gemini, saltá este paso.

### 5. Cargá los secretos y variables en GitHub

En tu repositorio: **Settings → Secrets and variables → Actions**.

| Tipo | Nombre | Valor |
|---|---|---|
| Secret | `GMAIL_CLIENT_ID` | del paso 3 |
| Secret | `GMAIL_CLIENT_SECRET` | del paso 3 |
| Secret | `GMAIL_REFRESH_TOKEN` | del paso 3 |
| Secret (opcional) | `GEMINI_API_KEY` | del paso 4 |
| Variable (opcional) | `USE_GEMINI` | `false` para forzar solo-reglas |
| Variable (opcional) | `GEMINI_MODEL` | nombre de modelo, si el predeterminado dejara de estar disponible |

Con GitHub CLI también podés hacerlo desde la terminal, sin copiar valores a mano en el navegador:

```bash
gh secret set GMAIL_CLIENT_ID
gh secret set GMAIL_CLIENT_SECRET
gh secret set GMAIL_REFRESH_TOKEN
gh secret set GEMINI_API_KEY        # opcional
```

### 6. Adaptá `rules.yaml` a tu casilla

Editá `rules.yaml` (ver [Cómo escribir reglas](#cómo-escribir-reglas)) y hacé commit. Los ejemplos incluidos son internacionales y genéricos: reemplazalos por los remitentes que realmente recibís.

### 7. Creá las etiquetas en Gmail

Una sola vez, desde tu computadora y con tu `.env` completo (ver *Uso local*):

```bash
python -m inbox_labeler labels
```

Crea las etiquetas que figuran en `rules.yaml` y no existen todavía. Repetilo cada vez que agregues o renombres una etiqueta.

### 8. Probá en vista previa

En **Actions → Inbox labeler → Run workflow** dejá *apply* sin marcar. Al terminar, abrí el **Summary** de la corrida: muestra cuántos mensajes se etiquetarían y por qué etiqueta, sin modificar nada. Cuando te convenza, ejecutalo de nuevo con *apply* marcado y revisá Gmail.

### 9. Activá la ejecución diaria

Creá la **variable** `ENABLE_SCHEDULE` con valor `true` (Settings → Secrets and variables → Actions → Variables). El workflow corre todos los días a las 09:00 UTC; cambiá el `cron` en `.github/workflows/labeler.yml` si querés otro horario (GitHub usa UTC).

## Uso local (opcional)

Copiá `.env.example` a `.env` y completá los valores.

```bash
python -m inbox_labeler check                 # verifica la conexión (solo imprime un conteo)
python -m inbox_labeler run                   # igual que la corrida diaria, en vista previa
python -m inbox_labeler run --apply           # agrega etiquetas de verdad
python -m inbox_labeler run --days 30 --max-messages 500 --apply   # ventana más amplia
python -m inbox_labeler run --verbose         # además imprime remitente y asunto de cada mensaje
```

`--verbose` **sí imprime remitentes y asuntos en tu terminal**, por eso solo funciona en local (está bloqueado en GitHub Actions).

## Cómo escribir reglas

`rules.yaml` define las etiquetas, su prioridad y sus reglas:

```yaml
Promotions:                       # nombre de la etiqueta en Gmail
  description: >-                 # Gemini lo usa para decidir; escribilo claro
    A non-financial merchant marketing offer, sale, coupon, or retail newsletter.
  rules:
    - senders: [newsletter, marketing]   # texto contenido en la DIRECCIÓN del remitente
      keywords: [sale, "% off"]          # texto contenido en el ASUNTO
```

- **El orden importa:** la primera etiqueta cuya regla coincida gana. Poné arriba las más específicas.
- Un grupo con **`senders` y `keywords`** exige ambos; con solo `senders`, basta el remitente; con solo `keywords`, basta el asunto.
- La búsqueda ignora mayúsculas y acentos.
- **Poné comillas** a las palabras que YAML interpreta como booleanos: `"off"`, `"no"`, `"yes"`. Si te olvidás, el programa lo avisa con un error claro.
- Para cambiar el conjunto de etiquetas **no hay que tocar código**: agregá, quitá o renombrá claves en `rules.yaml`, ejecutá `python -m inbox_labeler labels` y listo.
- Consejo: empezá con pocas reglas, mirá con `run --verbose` qué queda sin etiqueta y agregá reglas de a poco.
- Podés usar otro archivo definiendo la variable de entorno `RULES_PATH`.

## Recomendaciones de uso

- **Empezá siempre en vista previa** y revisá los resultados antes de aplicar.
- Las etiquetas **no mueven** los mensajes: siguen en la bandeja. Si querés que se salten la bandeja o se archiven, creá filtros en Gmail basados en las etiquetas; el proyecto no lo hace por vos a propósito.
- **Cuota de Gemini:** el nivel gratuito tiene límites por minuto y por día. El código espacia las llamadas para respetarlos. Si se agota la cuota diaria, las reglas siguen funcionando y los mensajes que quedaron sin clasificar se reintentan en la próxima corrida, mientras estén dentro de la ventana `--days` (por defecto, 2 días).
- **Costo:** Gmail API y el nivel gratuito de Gemini no tienen costo, y una corrida diaria dura pocos minutos de GitHub Actions. Verificá la cuota gratuita de Actions de tu plan para repositorios privados.
- En repositorios **públicos**, GitHub desactiva los workflows programados tras 60 días sin actividad. Tu copia debería ser privada de todos modos (ver Privacidad).
- Si sospechás que un secreto se filtró: revocá el acceso en <https://myaccount.google.com/permissions>, volvé a ejecutar `python -m inbox_labeler token` y actualizá los secretos.

## Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `invalid_grant` | Token vencido (app en *Testing*) o acceso revocado | Pasá la app a *In production* y repetí el paso 3 |
| `Missing Gmail label 'X'` en el resumen | La etiqueta existe en `rules.yaml` pero no en Gmail | Ejecutá `python -m inbox_labeler labels` |
| `Missing environment variables` | Faltan secretos o `.env` | Revisá el paso 5 (o tu `.env` en uso local) |
| `RulesError: …` | Error de estructura en `rules.yaml` | El mensaje indica la etiqueta y la regla |
| La corrida programada no se ejecuta | Falta la variable `ENABLE_SCHEDULE=true`, o el workflow no está en la rama principal | Revisá el paso 9; recordá que el horario es UTC |
| Errores `429` de Gemini | Cuota del nivel gratuito | Esperá; o usá solo-reglas (`USE_GEMINI=false`) |
| Gemini informa un modelo no disponible | Google retiró el modelo predeterminado | Definí la variable `GEMINI_MODEL` con un modelo vigente (ver la documentación de Gemini) |

## Estructura del proyecto

```
rules.yaml                 Etiquetas, prioridad, descripciones y reglas (lo único que tenés que editar)
inbox_labeler/
  rules.py                 Carga y valida las reglas; clasifica por remitente/asunto
  gemini.py, pipeline.py   Respaldo opcional con Gemini; las reglas van primero
  auth.py                  Cliente de Gmail y obtención del token (una sola vez)
  gmail.py                 Etiquetas, lectura de cabeceras y reintentos acotados
  report.py                Resumen con contadores en la pestaña Summary de cada corrida
  __main__.py              Comandos: run, labels, check, token
tests/                     Tests con clientes falsos: sin credenciales ni red
.github/workflows/labeler.yml   Corrida diaria / manual
```

## Tests

```bash
python -m tests
```

## Ideas a futuro

- Un asistente de configuración (`python -m inbox_labeler setup`) que guíe el alta y cargue los secretos con `gh secret set`. Algunos pasos de Google Cloud son manuales por diseño de Google, así que la automatización total no es posible.
- Plantillas de reglas por país e idioma.
- Filtros opcionales de Gmail (archivar, marcar como leído) como paso explícito y separado.

## Licencia

[MIT](LICENSE). Proyecto personal y educativo, no afiliado a Google ni a GitHub. Usalo bajo tu responsabilidad y empezá siempre con una vista previa.
