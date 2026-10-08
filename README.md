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
- **Vista previa por defecto.** Sin `--apply` no se modifica nada. Las ejecuciones manuales en GitHub Actions también son vista previa salvo que marques *Apply*.
- **Las corridas programadas no crean etiquetas.** Crear etiquetas es un paso aparte y explícito.
- **Los logs no filtran tu correo.** El log y el resumen de cada corrida tienen solo contadores e ids de mensaje, nunca remitentes ni asuntos. `--verbose` (que sí los imprime) está bloqueado dentro de GitHub Actions.
- **Gemini es opcional.** Sin `GEMINI_API_KEY`, o con `USE_GEMINI=false`, no se envía ningún dato a Gemini.

## Privacidad

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

En la página de este repositorio usá **Use this template → Create a new repository**, elegí **Private** y poné el nombre que quieras. Esto crea la copia en GitHub; todavía no la tenés en tu computadora.

### 2. Descargala a tu computadora

Necesitás [Git](https://git-scm.com/downloads) y [Python 3.12 o superior](https://www.python.org/downloads/) (en Windows, tildá **Add python.exe to PATH** al instalar). Abrí una terminal y ejecutá, con el nombre de **tu** copia:

```bash
git clone https://github.com/<tu-usuario>/<tu-repo>.git
cd <tu-repo>
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> En PowerShell, si el `Activate.ps1` falla por la política de ejecución, corré una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repetí.

### 3. Creá las credenciales de Google

Los menús de Google Cloud cambian con frecuencia; buscá los términos en inglés. **Hacé todo esto antes de generar el token** (paso 4).

1. En <https://console.cloud.google.com/> creá un proyecto nuevo.
2. Habilitá **Gmail API** (APIs & Services → Library).
3. Entrá a la pestaña **Credentials** de Gmail API: ahí aparece el botón para configurar la **pantalla de consentimiento** (Google Auth Platform). Completá:
   - **App information:** nombre a gusto y tu email como contacto.
   - **Audience:** *External* (usuarios externos).
   - **Contact information:** tu email.
4. En **Branding**, completá lo que Google pide para poder publicar la app: la página principal y la política de privacidad. Podés usar la de este template:
   - Página principal: `https://github.com/Nahuununez/inbox-labeler`
   - Política de privacidad: `https://github.com/Nahuununez/inbox-labeler#privacidad`
   - Dominio autorizado: `github.com`
   - Logo y términos del servicio: dejalos vacíos.
5. En **Data Access**, agregá el scope `https://www.googleapis.com/auth/gmail.modify`.
6. En **Audience**, apretá **Publish app** para pasar a *In production*.
7. En **Credentials → Create credentials → OAuth client ID**, tipo **Desktop app**. Descargá el JSON y guardalo en la carpeta del proyecto como `client_secret.json` (Google lo descarga con un nombre largo: renombralo).

> **Por qué publicar antes del token.** Mientras la app esté en *Testing*, Google vence el refresh token a los **7 días** y las corridas fallan con `invalid_grant`. Como la app es solo tuya y no está verificada, Google mostrará una advertencia al autorizar; es esperable.

### 4. Obtené el token (una sola vez)

```bash
python -m inbox_labeler token
```

Se abre el navegador, aceptás los permisos y la terminal imprime tres valores: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` y `GMAIL_REFRESH_TOKEN`. **Tratalos como contraseñas**: no los pegues en chats, issues ni commits.

Creá tu `.env` (`cp .env.example .env`; en PowerShell `Copy-Item .env.example .env`), pegá esos tres valores y verificá:

```bash
python -m inbox_labeler check
```

Debe decir `Connected to Gmail.` y la cantidad de mensajes de tu casilla.

### 5. (Opcional) API key de Gemini

En <https://aistudio.google.com/> apretá **Get API key / Create API key** (ignorá los avisos de *Upgrade*: el nivel gratuito alcanza). Pegala en tu `.env` como `GEMINI_API_KEY` y volvé a ejecutar `python -m inbox_labeler check`: además de Gmail prueba el modelo con un mensaje ficticio (no envía nada de tu casilla) y muestra cuánto tardó. Si no querés enviar nada a Gemini, saltá este paso.

El modelo predeterminado es `gemini-3.1-flash-lite`. Si `check` informa `FAILED` (modelo saturado o retirado), listá los disponibles con `python -m inbox_labeler models`, probá otro con `GEMINI_MODEL=<nombre>` en tu `.env` y evitá los alias tipo `*-latest`, que cambian de modelo sin avisar.

### 6. Cargá los secretos y variables en GitHub

En tu repositorio: **Settings → Secrets and variables → Actions**.

| Tipo | Nombre | Valor |
|---|---|---|
| Secret | `GMAIL_CLIENT_ID` | del paso 4 |
| Secret | `GMAIL_CLIENT_SECRET` | del paso 4 |
| Secret | `GMAIL_REFRESH_TOKEN` | del paso 4 |
| Secret (opcional) | `GEMINI_API_KEY` | del paso 5 |
| Variable (opcional) | `USE_GEMINI` | `false` para forzar solo-reglas |
| Variable (opcional) | `GEMINI_MODEL` | el modelo que te funcionó en `check` |

### 7. Adaptá `rules.yaml` a tu casilla

Editá `rules.yaml` (ver [Cómo escribir reglas](#cómo-escribir-reglas)) y hacé commit y push. Los ejemplos incluidos son genéricos: reemplazalos por los remitentes que realmente recibís. Una etiqueta con solo `description` (sin reglas) es válida: la decide Gemini.

### 8. Creá las etiquetas en Gmail

Una sola vez, desde tu computadora:

```bash
python -m inbox_labeler labels
```

Crea las etiquetas de `rules.yaml` que no existen todavía. Repetilo cada vez que agregues o renombres una etiqueta.

### 9. Probá en vista previa

En **Actions → Inbox labeler → Run workflow** (botón desplegable a la derecha) dejá **Apply** sin marcar y, para la primera prueba, poné *days* en `1` y *max messages* en `20`. Al terminar, abrí el **Summary** de la corrida: muestra cuántos mensajes se etiquetarían y por qué etiqueta, sin modificar nada.

Con Gemini activado, cada mensaje sin regla tarda unos 8 segundos (20 mensajes ≈ 3 minutos; 100 pueden tardar 8-15 minutos). Si no querés esperar, la primera prueba puede ser solo con reglas (`USE_GEMINI=false`). Cuando te convenza, ejecutalo de nuevo con **Apply** marcado y revisá Gmail.

### 10. Activá la ejecución diaria

Creá la **variable** `ENABLE_SCHEDULE` con valor `true` (Settings → Secrets and variables → Actions → Variables). El workflow corre todos los días a las 09:00 UTC (06:00 en Argentina); cambiá el `cron` en `.github/workflows/labeler.yml` si querés otro horario.

## Uso local (opcional)

Con tu `.env` completo (pasos 4 y 5):

```bash
python -m inbox_labeler check                 # verifica Gmail y el modelo de Gemini (solo imprime conteos)
python -m inbox_labeler models                # lista los modelos de Gemini disponibles
python -m inbox_labeler labels                # crea las etiquetas (antes de aplicar)
python -m inbox_labeler run                   # igual que la corrida diaria, en vista previa
python -m inbox_labeler run --apply           # agrega etiquetas de verdad
python -m inbox_labeler run --days 30 --max-messages 500 --apply   # ventana más amplia (el tope es 500)
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
- **Cuota de Gemini:** el nivel gratuito tiene límites por minuto y por día. El código espacia las llamadas para respetarlos. Si se agota la cuota, las reglas siguen funcionando y los mensajes que Gemini no llegó a clasificar se reintentan en cada corrida (y consumen cuota) mientras estén dentro de la ventana `--days` (por defecto, 2 días). Si Gemini te resulta inestable, empezá solo con reglas.
- **Costo:** Gmail API y el nivel gratuito de Gemini no tienen costo, y una corrida diaria dura pocos minutos de GitHub Actions. Verificá la cuota gratuita de Actions de tu plan para repositorios privados.
- En repositorios **públicos**, GitHub desactiva los workflows programados tras 60 días sin actividad. Tu copia debería ser privada de todos modos (ver Privacidad).
- Si sospechás que un secreto se filtró: revocá el acceso en <https://myaccount.google.com/permissions>, volvé a ejecutar `python -m inbox_labeler token` y actualizá los secretos.

## Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `invalid_grant` | Token vencido (app en *Testing*) o acceso revocado | Pasá la app a *In production* y repetí el paso 4 |
| `Missing Gmail label 'X'` en el resumen | La etiqueta existe en `rules.yaml` pero no en Gmail | Ejecutá `python -m inbox_labeler labels` |
| `Missing environment variables` | Faltan secretos o `.env` | Revisá el paso 6 (o tu `.env` en uso local) |
| `RulesError: …` | Error de estructura en `rules.yaml` | El mensaje indica la etiqueta y la regla |
| La corrida programada no se ejecuta | Falta la variable `ENABLE_SCHEDULE=true`, o el workflow no está en la rama principal | Revisá el paso 10; recordá que el horario es UTC |
| Gemini 503/504 (`high demand`, `DEADLINE_EXCEEDED`) o `read operation timed out` | El modelo está saturado | Esperá y reintentá, probá otro `GEMINI_MODEL` (`python -m inbox_labeler models`) o usá solo-reglas (`USE_GEMINI=false`) |
| `Gemini stopped for the rest of this run` | Cuota agotada o errores repetidos: el programa deja de llamar a Gemini en esa corrida | Las reglas siguen funcionando; los mensajes sin etiquetar se reintentan en la próxima corrida |
| Errores `429` de Gemini | Cuota del nivel gratuito (unas 12 llamadas por minuto) | Esperá; o usá solo-reglas |
| Gemini informa un modelo no disponible | Google retiró el modelo | Definí `GEMINI_MODEL` con uno vigente (`python -m inbox_labeler models`) |
| Gmail `rateLimitExceeded` | Cuota por minuto de Gmail | Se reintenta solo; si persiste, bajá `--max-messages` |
| PowerShell no deja activar el entorno | Política de ejecución | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## Estructura del proyecto

```
rules.yaml                 Etiquetas, prioridad, descripciones y reglas (lo único que tenés que editar)
inbox_labeler/
  rules.py                 Carga y valida las reglas; clasifica por remitente/asunto
  gemini.py, pipeline.py   Respaldo opcional con Gemini; las reglas van primero
  auth.py                  Cliente de Gmail y obtención del token (una sola vez)
  gmail.py                 Etiquetas, lectura de cabeceras y reintentos acotados
  report.py                Resumen con contadores en la pestaña Summary de cada corrida
  __main__.py              Comandos: run, labels, check, models, token
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
