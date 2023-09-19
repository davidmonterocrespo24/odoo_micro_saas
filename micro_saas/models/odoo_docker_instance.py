import os
import socket
import subprocess
from datetime import datetime

from odoo import models, fields, api
from odoo.modules.module import get_resource_path


class OdooDockerInstance(models.Model):
    _name = 'odoo.docker.instance'
    _description = 'Odoo Docker Instance'

    name = fields.Char(string='Instance Name', required=True)
    state = fields.Selection([('draft', 'Draft'),('stopped', 'Stopped'), ('running', 'Running'),('cancel', 'Cancel')], string='State', default='draft')
    http_port = fields.Char(string='HTTP Port')
    longpolling_port = fields.Char(string='Longpolling Port')

    instance_url = fields.Char(string='Instance URL', compute='_compute_instance_url', store=True)
    repository_line = fields.One2many('repository.repo.line', 'instance_id', string='Repository and Branch')

    log = fields.Text(string='Log')
    addons_path = fields.Char(string='Addons Path', compute='_compute_addons_path', store=True)

    @api.depends('repository_line')
    def _compute_addons_path(self):
        for instance in self:
            addons_path = []
            for line in instance.repository_line:
                repo_path = name_repo_url = line.repository_id.name.split('/')[-1]
                repo_path = name_repo_url.replace('.git', '').replace('.', '_').replace('-', '_').replace(' ', '_').replace(
                    '/', '_').replace('\\', '_') + "_branch_" + line.name.replace('.', '_')
                addons_path.append("/mnt/extra-addons/"+repo_path)
            instance.addons_path = ','.join(addons_path)

    def add_to_log(self, message):
        """Agrega un mensaje al registro (log) y lo limpia si supera 1000 caracteres."""
        now = datetime.now()
        new_log = "\n#" + str(now.strftime("%m/%d/%Y, %H:%M:%S")) + " " + str(message) + " " + str(self.log)
        if len(new_log) > 1000:
            # Si el registro supera los 1000 caracteres, límpialo
            new_log = "\n#" + str(now.strftime("%m/%d/%Y, %H:%M:%S")) + " " + str(message)
        self.log = new_log

    @api.depends('http_port')
    def _compute_instance_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        # dividir la url en partes para obtener la url
        base_url = base_url.split(':')
        base_url = base_url[0] + ':' + base_url[1] + ':'

        for instance in self:
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
        instance_data_path = get_resource_path('micro_saas', 'data')
        instance_data_path = os.path.join(instance_data_path, self.name)
        if not os.path.exists(instance_data_path):
            os.makedirs(instance_data_path)
        modified_path = os.path.join(instance_data_path, 'docker-compose.yml')

        # Lee el archivo de plantilla
        with open(template_path, "r") as template_file:
            template_content = template_file.read()

        # Reemplaza las variables en el archivo de plantilla
        modified_content = template_content.replace("{{HTTP-PORT}}", str(http_port)).replace("{{LONGPOLLING-PORT}}",
                                                                                             str(longpolling_port)).replace(
            "{{INSTANCE-NAME}}", self.name).replace("{{INSTANCE-DIR}}", instance_data_path)

        # Guarda el archivo docker-compose.yml modificado
        with open(modified_path, "w") as modified_file:
            modified_file.write(modified_content)

    def _get_repo_path(self, repository_name, instance):
        intance_path = os.path.join(get_resource_path('micro_saas', 'data'), instance.name)
        name_repo_url = repository_name.repository_id.name.split('/')[-1]
        name = name_repo_url.replace('.git', '').replace('.', '_').replace('-', '_').replace(' ', '_').replace(
            '/', '_').replace('\\', '_') + "_branch_" + repository_name.name.replace('.', '_')
        repo_path = os.path.join(intance_path, "addons", name)
        return repo_path

    def _clone_repositories(self):
        for instance in self:
            for line in instance.repository_line:
                repo_path = self._get_repo_path(line, instance)
                if not os.path.exists(repo_path):
                    os.makedirs(repo_path)
                try:
                    cmd = f"git clone -b {line.name} {line.repository_id.name} {repo_path}"
                    subprocess.run(cmd, shell=True, check=True)
                    self.add_to_log(f"[INFO] Repositorio clonado: {line.repository_id.name} (Rama: {line.name})")
                    line.is_clone = True
                except Exception as e:
                    self.add_to_log(
                        f"[ERROR] Error al clonar el repositorio: {line.repository_id.name} (Rama: {line.name})")
                    # error trace
                    if hasattr(e, 'stderr') and e.stderr:
                        self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
                    else:
                        self.add_to_log("[ERROR]  " + str(e))

    def _create_odoo_conf(self):
        for instance in self:
            odoo_conf_path = os.path.join(get_resource_path('micro_saas', 'data', instance.name), "etc", 'odoo.conf')
            if not os.path.exists(os.path.dirname(odoo_conf_path)):
                os.makedirs(os.path.dirname(odoo_conf_path))
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
                if hasattr(e, 'stderr') and e.stderr:
                    self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
                else:
                    self.add_to_log("[ERROR]  " + str(e))
                self.write({'state': 'stopped'})

    def start_instance(self):
        # Obtén un puerto disponible
        self.add_to_log("[INFO] Iniciando instancia de Odoo")
        self.add_to_log("[INFO] Obteniendo puerto disponible")
        http_port = self._get_available_port()
        longpolling_port = self._get_available_port(start_port=http_port + 1)

        self.add_to_log("[INFO] Puerto disponible: " + str(http_port) + " Puerto longpolling: " + str(longpolling_port))

        # Actualiza el archivo docker-compose con el puerto
        print("Actualizando archivo docker-compose")
        self._update_docker_compose_file(http_port, longpolling_port)
        self.http_port = str(http_port)
        self.longpolling_port = str(longpolling_port)

        # Clonar repositorios y crear odoo.conf
        self._clone_repositories()
        self._create_odoo_conf()

        # Ruta al archivo docker-compose.yml modificado
        self.add_to_log("[INFO] Ruta al archivo docker-compose.yml modificado")
        modified_path = get_resource_path('micro_saas', 'data', self.name) + '/docker-compose.yml'

        # cargar el archivo docker-compose.yml en el campo binario docker_compose_file
        try:
            # Ejecuta el comando de Docker Compose para levantar la instancia
            cmd = f"docker-compose -f {modified_path} up -d"
            result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.add_to_log("[INFO] Comando Docker Compose ejecutado exitosamente:")
            self.write({'state': 'running'})
        except Exception as e:
            # Maneja cualquier otro error que pueda ocurrir al ejecutar Docker Compose
            # Imprimir el stderr para obtener más detalles
            self.add_to_log("[ERROR] Error al ejecutar el comando Docker Compose:")
            self.add_to_log("[ERROR]  " + e.stderr.decode('utf-8'))
            self.write({'state': 'stopped'})

    def stop_instance(self):
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Deteniendo instancia de Odoo")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = get_resource_path('micro_saas', 'data', instance.name) + '/docker-compose.yml'

                try:
                    # Ejecuta el comando de Docker Compose para detener la instancia
                    cmd = f"docker-compose -f {modified_path} down"
                    subprocess.run(cmd, shell=True, check=True)
                    # Cambia la propiedad 'state' a 'stopped'
                    instance.write({'state': 'stopped'})
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    self.add_to_log(f"[ERROR] Error al detener la instancia de Odoo: {str(e)}")

    def restart_instance(self):
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Reiniciando instancia de Odoo")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = get_resource_path('micro_saas', 'data', instance.name) + '/docker-compose.yml'

                try:
                    # Ejecuta el comando de Docker Compose para detener la instancia
                    cmd = f"docker-compose -f {modified_path} restart"
                    subprocess.run(cmd, shell=True, check=True)
                    # Cambia la propiedad 'state' a 'stopped'
                    instance.write({'state': 'running'})
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    self.add_to_log(f"[ERROR] Error al detener la instancia de Odoo: {str(e)}")
                    self.write({'state': 'stopped'})

    def unlink(self):
        # Detener y eliminar los contenedores asociados antes de borrar el registro
        for instance in self:
            if instance.state == 'running':
                self.add_to_log("[INFO] Eliminando instancia de Odoo")
                # Ruta al archivo docker-compose.yml modificado
                modified_path = get_resource_path('micro_saas', 'data', instance.name) + '/docker-compose.yml'

                try:
                    # Ejecuta el comando de Docker Compose para detener y eliminar los contenedores
                    cmd = f"docker-compose -f {modified_path} down"
                    subprocess.run(cmd, shell=True, check=True)
                    # Borra los archivos de la instancia

                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    pass
                try:

                    path = get_resource_path('micro_saas', 'data', instance.name)
                    # borra todos los archivos de la instancia y carpetas
                    for root, dirs, files in os.walk(path, topdown=False):
                        for name in files:
                            os.remove(os.path.join(root, name))
                        for name in dirs:
                            os.rmdir(os.path.join(root, name))
                except Exception as e:
                    # Maneja cualquier error que pueda ocurrir al detener Docker Compose
                    pass

        # Luego, elimina el registro del modelo
        return super(OdooDockerInstance, self).unlink()


    def cancel_instance(self):
        self.write({'state': 'cancel'})