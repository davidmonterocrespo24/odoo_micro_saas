import os
import socket
import subprocess
from datetime import datetime
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)
from odoo import models, fields, api
from odoo.modules.module import get_resource_path


class OdooDockerInstance(models.Model):
    _name = 'odoo.docker.instance'
    _inherit = "docker.compose.template"
    _description = 'Odoo Docker Instance'

    name = fields.Char(string='Instance Name', required=True)
    state = fields.Selection([('draft', 'Draft'), ('stopped', 'Stopped'), ('running', 'Running'), ('error', 'Error')],
                             string='State', default='draft')
    http_port = fields.Char(string='HTTP Port' , required=True)
    longpolling_port = fields.Char(string='Longpolling Port' , required=True)

    instance_url = fields.Char(string='Instance URL', compute='_compute_instance_url', store=True)
    repository_line = fields.One2many('repository.repo.line', 'instance_id', string='Repository and Branch')

    log = fields.Html(string='Log')
    addons_path = fields.Char(string='Addons Path', compute='_compute_addons_path', store=True)
    user_path = fields.Char(string='User Path', compute='_compute_user_path', store=True)
    instance_data_path = fields.Char(string='Instance Data Path', compute='_compute_user_path', store=True)
    template_id = fields.Many2one('docker.compose.template', string='Template')



    @api.depends('template_id')
    def onchange_template_id(self):
        for instance in self:
            if instance.template_id:
                _logger.info("Value Template ID: %s", instance.template_id)
                instance.template_dc_body = instance.template_id.template_dc_body
                instance.tag_ids = instance.template_id.tag_ids
                instance.repository_line = instance.template_id.repository_line
                self._compute_variable_ids()
                instance.result_dc_body = self._get_formatted_body(demo_fallback=True)
            else:
                _logger.info("Template ID: %s", instance.template_id)

    @api.depends('name')
    def _compute_user_path(self):
        for instance in self:
            if not instance.name:
                continue
            instance.user_path = os.path.expanduser('~')
            instance.instance_data_path = os.path.join(instance.user_path, 'odoo_docker', 'data', instance.name)
            instance.result_dc_body = self._get_formatted_body(demo_fallback=True)

    @api.depends('repository_line')
    def _compute_addons_path(self):
        for instance in self:
            if not instance.repository_line:
                continue
            addons_path = []
            for line in instance.repository_line:
                addons_path.append("/mnt/extra-addons/" + self._get_repo_name(line))
            instance.addons_path = ','.join(addons_path)

    def add_to_log(self, message):
        """Agrega un mensaje al registro (log) y lo limpia si supera 1000 caracteres."""
        now = datetime.now()
        new_log = "</br> \n#" + str(now.strftime("%m/%d/%Y, %H:%M:%S")) + " " + str(message) + " " + str(self.log)
        if len(new_log) > 1000:
            # Si el registro supera los 1000 caracteres, límpialo
            new_log = "</br>" + str(now.strftime("%m/%d/%Y, %H:%M:%S")) + " " + str(message)
        self.log = new_log

    @api.depends('http_port')
    def _compute_instance_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        # dividir la url en partes para obtener la url
        base_url = base_url.split(':')
        base_url = base_url[0] + ':' + base_url[1] + ':'

        for instance in self:
            if not instance.http_port:
                continue
            instance_url = f"{base_url}{instance.http_port}"
            instance.instance_url = instance_url

    def open_instance_url(self):
        for instance in self:
            if instance.http_port:
                url = instance.instance_url
                return {
                    'type': 'ir.actions.act_url',
                    'url': url,
                    'target': 'new',
                }

    def _get_available_port(self, start_port=8069, end_port=9000):
        # Define el rango de puertos en el que deseas buscar disponibles
        # buscar todos los puertos de las instancias
        instances = self.env['odoo.docker.instance'].search([])
        # crear una lista con los puertos de las instancias
        ports = []
        for instance in instances:
            ports.append(instance.http_port)
            ports.append(instance.longpolling_port)

        for port in range(start_port, end_port + 1):
            # Si el puerto ya está en uso, continúa con el siguiente
            if port in ports:
                continue
            # Intenta crear un socket en el puerto
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # Establece un tiempo de espera para la conexión

            try:
                # Intenta vincular el socket al puerto
                sock.bind(("0.0.0.0", port))
                return port  # Si tiene éxito, el puerto está disponible
            except Exception as e:
                # Si no tiene éxito, el puerto ya está en uso
                pass
            finally:
                sock.close()

        # Si no se encuentra ningún puerto disponible en el rango especificado
        self.add_to_log("[ERROR] No se encontraron puertos disponibles en el rango especificado.")

    def _update_docker_compose_file(self, http_port, longpolling_port):
        # Ruta al archivo docker-compose.yml de plantilla
        template_path = get_resource_path('micro_saas', 'data', 'docker-compose-template.yml')
        if not os.path.exists(template_path):
            self.add_to_log("[ERROR] No se encontró el archivo docker-compose-template.yml")

        # Ruta donde se guardará el archivo docker-compose.yml modificado
        if not os.path.exists(self.instance_data_path):
            _logger.info("Creating directory %s", self.instance_data_path)
            self._makedirs(self.instance_data_path)
        modified_path = os.path.join(self.instance_data_path, 'docker-compose.yml')

        # Lee el archivo de plantilla
        with open(template_path, "r") as template_file:
            template_content = template_file.read()

        # Reemplaza las variables en el archivo de plantilla
        modified_content = template_content.replace("{{HTTP-PORT}}", str(http_port)).replace("{{LONGPOLLING-PORT}}",
                                                                                             str(longpolling_port)).replace(
            "{{INSTANCE-NAME}}", self.name).replace("{{INSTANCE-DIR}}", self.instance_data_path)

        # Guarda el archivo docker-compose.yml modificado
        with open(modified_path, "w") as modified_file:
            modified_file.write(modified_content)

    def _get_repo_name(self, line):
        if not line.repository_id or not line.name or not line.repository_id.name:
            return ''
        name_repo_url = line.repository_id.name.split('/')[-1]
        name = name_repo_url.replace('.git', '').replace('.', '_').replace('-', '_').replace(' ', '_').replace(
            '/', '_').replace('\\', '_') + "_branch_" + line.name.replace('.', '_')
        return name

    def _makedirs(self, path):
        try:
            os.makedirs(path)
        except Exception as e:
            raise UserError(
                f"Error while creating directory {path} : {str(e)}")

    def _clone_repositories(self):
        for instance in self:
            for line in instance.repository_line:
                repo_name = self._get_repo_name(line)
                repo_path = os.path.join(instance.instance_data_path, "addons", repo_name)
                if not os.path.exists(repo_path):
                    self._makedirs(repo_path)
                try:
                    cmd = f"git clone {line.repository_id.name} -b {line.name} {repo_path}"
                    subprocess.run(cmd, shell=True, check=True)
                    self.add_to_log(f"[INFO] Repository cloned: {line.repository_id.name} (Branch: {line.name})")
                    line.is_clone = True
                except Exception as e:
                    self.add_to_log(
                        f"[ERROR] Error to clone repository: {line.repository_id.name} (Branch: {line.name})")
                    # error trace
                    if hasattr(e, 'stderr') and e.stderr:
                        self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
                    else:
                        self.add_to_log("[ERROR]  " + str(e))

    def _create_odoo_conf(self):
        for instance in self:
            odoo_conf_path = os.path.join(self.instance_data_path, "etc", 'odoo.conf')
            if not os.path.exists(os.path.dirname(odoo_conf_path)):
                self._makedirs(os.path.dirname(odoo_conf_path))
            addons_path = instance.addons_path
            try:
                with open(odoo_conf_path, 'w') as odoo_conf_file:
                    odoo_conf_file.write(f"[options]\naddons_path = {addons_path}\n")
                    odoo_conf_file.write("admin_passwd = admin\n")
                    odoo_conf_file.write("data_dir = /var/lib/odoo\n")
                    odoo_conf_file.write("logfile = /var/log/odoo/odoo.log\n")
                self.add_to_log(f"[INFO] Archivo odoo.conf creado exitosamente en {odoo_conf_path}")
            except Exception as e:
                self.add_to_log(f"[ERROR] Error al crear el archivo odoo.conf en {odoo_conf_path}")
                self.write({'state': 'error'})
                if hasattr(e, 'stderr') and e.stderr:
                    self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
                else:
                    self.add_to_log("[ERROR]  " + str(e))
                self.write({'state': 'stopped'})

    @api.model
    def _is_docker_installed(self):
        try:
            subprocess.run(["docker", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return True
        except Exception as e:
            self.add_to_log("[ERROR] Docker don't installed in the system.")
            self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8') if hasattr(e, 'stderr') else str(e))
            self.write({'state': 'error'})
            return False

    @api.model
    def _is_docker_compose_installed(self):
        try:
            subprocess.run(["docker-compose", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return True
        except Exception as e:
            self.add_to_log("[ERROR] Docker Compose don't installed in the system.")
            self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8') if hasattr(e, 'stderr') else str(e))
            self.write({'state': 'error'})
            return False

    def start_instance(self):
        # Obtén un puerto disponible
        if self._is_docker_installed() or self._is_docker_compose_installed():
            return False
        self.add_to_log("[INFO] Starting Odoo Instance")
        self.add_to_log("[INFO] Finding available port")
        http_port = self._get_available_port()
        longpolling_port = self._get_available_port(start_port=http_port + 1)

        self.add_to_log("[INFO] Port available: " + str(http_port) + " and " + str(longpolling_port))

        # Actualiza el archivo docker-compose con el puerto
        self._update_docker_compose_file(http_port, longpolling_port)
        self.http_port = str(http_port)
        self.longpolling_port = str(longpolling_port)

        # Clonar repositorios y crear odoo.conf
        self._clone_repositories()
        self._create_odoo_conf()

        # Ruta al archivo docker-compose.yml modificado
        self.add_to_log("[INFO] Path to modified docker-compose.yml file")
        modified_path = self.instance_data_path + '/docker-compose.yml'

        # cargar el archivo docker-compose.yml en el campo binario docker_compose_file
        try:
            # Ejecuta el comando de Docker Compose para levantar la instancia
            cmd = f"docker-compose -f {modified_path} up -d"
            result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.add_to_log("[INFO] Docker Compose command executed successfully")
            self.write({'state': 'running'})
        except Exception as e:
            # Maneja cualquier otro error que pueda ocurrir al ejecutar Docker Compose
            # Imprimir el stderr para obtener más detalles
            self.add_to_log("[ERROR] Error to execute docker-compose command")
            self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
            self.write({'state': 'error'})

    def stop_instance(self):
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Stopping Odoo Instance")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = instance.instance_data_path + '/docker-compose.yml'

                try:
                    # Ejecuta el comando de Docker Compose para detener la instancia
                    cmd = f"docker-compose -f {modified_path} down"
                    subprocess.run(cmd, shell=True, check=True)
                    # Cambia la propiedad 'state' a 'stopped'
                    instance.write({'state': 'stopped'})
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    self.add_to_log(f"[ERROR] Error to stop Odoo Instance: {str(e)}")

    def restart_instance(self):
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Restarting Odoo Instance")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = instance.instance_data_path + '/docker-compose.yml'
                try:
                    # Ejecuta el comando de Docker Compose para detener la instancia
                    cmd = f"docker-compose -f {modified_path} restart"
                    subprocess.run(cmd, shell=True, check=True)
                    # Cambia la propiedad 'state' a 'stopped'
                    instance.write({'state': 'running'})
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    self.add_to_log(f"[ERROR] Error to restart Odoo Instance: {str(e)}")
                    self.write({'state': 'stopped'})

    def unlink(self):
        # Detener y eliminar los contenedores asociados antes de borrar el registro
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Removing Odoo Instance")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = instance.instance_data_path + '/docker-compose.yml'

                try:
                    # Ejecuta el comando de Docker Compose para detener y eliminar los contenedores
                    cmd = f"docker-compose -f {modified_path} down"
                    subprocess.run(cmd, shell=True, check=True)
                    # Borra los archivos de la instancia

                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    pass
                try:
                    # borra todos los archivos de la instancia y carpetas
                    for root, dirs, files in os.walk(instance.instance_data_path, topdown=False):
                        for name in files:
                            os.remove(os.path.join(root, name))
                        for name in dirs:
                            os.rmdir(os.path.join(root, name))
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    pass

        # Luego, elimina el registro del modelo
        return super(OdooDockerInstance, self).unlink()
